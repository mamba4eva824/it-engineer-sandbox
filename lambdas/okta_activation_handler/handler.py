"""AWS Lambda handler for Okta event hooks → Slack #joiner-it-ops post.

Wired to a Lambda Function URL (HTTPS, IAM auth=NONE — Okta authenticates with
a shared secret in the Authorization header). Subscribes to one Okta event:

    user.account.update_password

…which fires when a user sets a password — both at first activation and on
every later password change. To distinguish "they just activated" from
"they're rotating their password," the handler dedupes by calling the Okta
Management API and checking the user's `lastLogin` field. If `lastLogin` is
None (or within seconds of the event), it's the activation flow → post to
Slack. Otherwise → silent skip + structured log line.

Two HTTP modes the handler must honor:

  GET  + x-okta-verification-challenge: <token>
       → respond {"verification": <token>} to activate the hook (one-time).

  POST + Authorization: <shared-secret>
       → parse data.events[*]; for matching event types, post to Slack.

Secrets pulled from AWS Secrets Manager at module load (cached for cold-start
amortization across reused executions). The Lambda's execution role is scoped
(in iam.tf) to GetSecretValue on exactly the secrets it needs.

Returns 200 fast even on Slack errors so Okta doesn't redeliver — CloudWatch
captures the post failure for the operator. (Production would use SQS for
retries; sandbox treats Slack as best-effort observability.)
"""

import json
import os
import time
import uuid
from typing import Any

import boto3
import jwt
import requests


SECRETS_REGION = os.environ.get("SECRETS_REGION", "us-east-1")
OKTA_SECRET_NAME = os.environ["OKTA_SECRET_NAME"]
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_BOT_TOKEN_SECRET_NAME"]
OKTA_API_CLIENT_ID_SECRET_NAME = os.environ["OKTA_API_CLIENT_ID_SECRET_NAME"]
OKTA_API_PRIVATE_KEY_SECRET_NAME = os.environ["OKTA_API_PRIVATE_KEY_SECRET_NAME"]
OKTA_API_KEY_ID_SECRET_NAME = os.environ["OKTA_API_KEY_ID_SECRET_NAME"]
OKTA_ORG_URL = os.environ["OKTA_ORG_URL"]
SLACK_TEAM_ID = os.environ.get("SLACK_TEAM_ID", "")
JOINER_CHANNEL_NAME = os.environ.get("JOINER_CHANNEL_NAME", "joiner-it-ops")

WATCHED_EVENT_TYPES = {"user.account.update_password"}

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)


def _fetch_secret(name: str) -> str:
    return _secrets_client.get_secret_value(SecretId=name)["SecretString"]


# Inbound + outbound auth secrets, fetched once at cold start.
_OKTA_SHARED_SECRET = _fetch_secret(OKTA_SECRET_NAME)
_SLACK_BOT_TOKEN = _fetch_secret(SLACK_BOT_TOKEN_SECRET_NAME)

# Okta Management API creds for the dedup lookup. Same shape as
# scripts/okta/_client.py — Private Key JWT client-credentials exchange.
_OKTA_API_CLIENT_ID = _fetch_secret(OKTA_API_CLIENT_ID_SECRET_NAME)
_OKTA_API_PRIVATE_KEY = _fetch_secret(OKTA_API_PRIVATE_KEY_SECRET_NAME)
_OKTA_API_KEY_ID = _fetch_secret(OKTA_API_KEY_ID_SECRET_NAME)

# Cached access token for warm Lambda execution context. Refreshed when the
# stored expiry approaches.
_okta_token_cache: dict = {"token": None, "expires_at": 0}


def _http_response(status: int, body: dict | None = None) -> dict:
    """Lambda Function URL response envelope."""
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body or {}),
    }


def _okta_access_token() -> str:
    """Return a valid Okta API access token, exchanging a JWT assertion if needed.

    Mirrors scripts/okta/_client.py:get_access_token(). Cache lifetime is the
    token's `expires_in` (default 1 hour) minus a 60-second skew buffer.
    """
    now = int(time.time())
    if _okta_token_cache["token"] and _okta_token_cache["expires_at"] - 60 > now:
        return _okta_token_cache["token"]

    token_url = f"{OKTA_ORG_URL.rstrip('/')}/oauth2/v1/token"
    pem = _OKTA_API_PRIVATE_KEY.strip().strip('"')
    if "\\n" in pem:
        pem = pem.replace("\\n", "\n")

    assertion = jwt.encode(
        payload={
            "iss": _OKTA_API_CLIENT_ID,
            "sub": _OKTA_API_CLIENT_ID,
            "aud": token_url,
            "iat": now,
            "exp": now + 300,
            "jti": uuid.uuid4().hex,
        },
        key=pem.encode(),
        algorithm="RS256",
        headers={"alg": "RS256", "kid": _OKTA_API_KEY_ID},
    )
    resp = requests.post(
        token_url,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "client_credentials",
            "scope": "okta.users.read",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        },
        timeout=10,
    )
    resp.raise_for_status()
    body = resp.json()
    _okta_token_cache["token"] = body["access_token"]
    _okta_token_cache["expires_at"] = now + int(body.get("expires_in", 3600))
    return body["access_token"]


def _is_first_activation(user_id: str) -> tuple[bool, str]:
    """Return (is_first_activation, reason).

    True when the user has never logged in (lastLogin is null/empty), which
    only happens during the activation flow. False on every subsequent
    password change. `reason` is a short string for the structured log line.
    """
    token = _okta_access_token()
    resp = requests.get(
        f"{OKTA_ORG_URL.rstrip('/')}/api/v1/users/{user_id}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        timeout=10,
    )
    if resp.status_code != 200:
        # Don't post on errors — false positives are worse than false negatives here.
        return False, f"okta_lookup_http_{resp.status_code}"
    user = resp.json()
    last_login = user.get("lastLogin")
    if not last_login:
        return True, "no_lastLogin_yet"
    return False, f"already_logged_in_at_{last_login}"


def _post_slack(channel_id: str, text: str, blocks: list) -> tuple[bool, str]:
    """chat.postMessage wrapper. Returns (ok, error|ts)."""
    resp = requests.post(
        "https://slack.com/api/chat.postMessage",
        headers={
            "Authorization": f"Bearer {_SLACK_BOT_TOKEN}",
            "Content-Type": "application/json; charset=utf-8",
        },
        json={"channel": channel_id, "text": text, "blocks": blocks},
        timeout=10,
    )
    body = resp.json()
    if not body.get("ok"):
        return False, body.get("error", "unknown")
    return True, body.get("ts", "")


def _resolve_or_create_channel(name: str) -> tuple[bool, str]:
    """Resolve channel by name, creating it if missing. Returns (ok, channel_id|error)."""
    if not SLACK_TEAM_ID:
        return False, "missing_team_id_env"
    headers = {"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"}

    # Try create first; cheap when channel doesn't exist, returns name_taken if it does.
    create_resp = requests.post(
        "https://slack.com/api/conversations.create",
        headers={**headers, "Content-Type": "application/json; charset=utf-8"},
        json={"name": name, "is_private": False, "team_id": SLACK_TEAM_ID},
        timeout=10,
    ).json()
    if create_resp.get("ok"):
        return True, create_resp["channel"]["id"]
    if create_resp.get("error") not in ("name_taken", "channel_name_already_taken"):
        return False, create_resp.get("error", "create_failed")

    # Channel exists — list and find it.
    cursor = ""
    while True:
        params = {"limit": "200", "types": "public_channel", "team_id": SLACK_TEAM_ID}
        if cursor:
            params["cursor"] = cursor
        list_resp = requests.get(
            "https://slack.com/api/conversations.list",
            headers=headers, params=params, timeout=15,
        ).json()
        if not list_resp.get("ok"):
            return False, list_resp.get("error", "list_failed")
        for ch in list_resp.get("channels", []):
            if ch.get("name") == name:
                return True, ch["id"]
        cursor = list_resp.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return False, "channel_not_found"


def _build_activation_message(login: str, full_name: str, event_time: str) -> tuple[str, list]:
    text = f":white_check_mark: *New hire activated Okta:* {full_name} ({login})"
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Login:*\n{login}"},
            {"type": "mrkdwn", "text": f"*Activated at:*\n{event_time}"},
            {"type": "mrkdwn", "text": "*Source:*\nOkta event hook → AWS Lambda"},
            {"type": "mrkdwn", "text": "*Status:*\nAccount active — full identity-layer access live"},
        ]},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "Posted by NovaTech IT Ops automation"},
        ]},
    ]
    return text, blocks


def _handle_event_post(event_payload: dict) -> dict:
    """Walk data.events[], dispatch a Slack post for each matching activation event.

    For each matching event, looks up the user via Okta API and only posts if
    `lastLogin` is empty — that's the first-activation signal. Subsequent
    password changes are skipped silently with a structured log line so the
    skip is auditable in CloudWatch.
    """
    events = event_payload.get("data", {}).get("events", []) or []
    posted = []
    skipped = []
    for ev in events:
        evtype = ev.get("eventType", "")
        if evtype not in WATCHED_EVENT_TYPES:
            skipped.append({"eventType": evtype, "reason": "not_watched"})
            continue

        actor = ev.get("actor", {}) or {}
        user_id = actor.get("id", "")
        login = actor.get("alternateId") or actor.get("displayName", "(unknown)")
        full_name = actor.get("displayName") or login
        event_time = ev.get("published", "(unknown)")

        if not user_id:
            skipped.append({"login": login, "reason": "no_actor_id"})
            continue

        is_first, why = _is_first_activation(user_id)
        if not is_first:
            skipped.append({"login": login, "reason": f"not_first_activation:{why}"})
            continue

        ok, channel_id = _resolve_or_create_channel(JOINER_CHANNEL_NAME)
        if not ok:
            skipped.append({"login": login, "reason": f"channel:{channel_id}"})
            continue
        text, blocks = _build_activation_message(login, full_name, event_time)
        ok, detail = _post_slack(channel_id, text, blocks)
        if ok:
            posted.append({"login": login, "ts": detail})
        else:
            skipped.append({"login": login, "reason": f"post:{detail}"})
    return {"posted": posted, "skipped": skipped}


def lambda_handler(event, context):
    """Lambda Function URL entry point.

    `event` is the Lambda URL event format (rawPath, headers, body, requestContext.http.method).
    """
    method = (
        event.get("requestContext", {})
        .get("http", {})
        .get("method", "POST")
        .upper()
    )
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    # GET → one-time verification challenge.
    if method == "GET":
        challenge = headers.get("x-okta-verification-challenge")
        if not challenge:
            return _http_response(400, {"error": "missing x-okta-verification-challenge header"})
        return _http_response(200, {"verification": challenge})

    # POST → event delivery; verify shared-secret Authorization header.
    if method != "POST":
        return _http_response(405, {"error": f"method {method} not allowed"})

    auth = headers.get("authorization", "")
    if auth != _OKTA_SHARED_SECRET:
        # Don't echo what we expected; just deny.
        return _http_response(401, {"error": "unauthorized"})

    raw_body = event.get("body") or "{}"
    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError as e:
        return _http_response(400, {"error": f"invalid json: {e}"})

    result = _handle_event_post(payload)
    # 200 always so Okta doesn't redeliver; details land in CloudWatch logs.
    print(json.dumps({"event": "okta_hook_processed", **result}))
    return _http_response(200, result)
