"""AWS Lambda handler for the ohmgym onboarding workflow.

Invoked by EventBridge Scheduler at 09:00 America/Los_Angeles daily. On each
invocation:

  1. Compute today_pt (overridable via event["override_date"] for replays).
  2. Query Okta Management API for users matching
       status eq "STAGED" and profile.startDate eq "<today_pt>"
     via the server-side `search` filter.
  3. For each matched user:
       a. DynamoDB GetItem on (run_date, user_id) — skip if already success.
       b. POST /api/v1/users/{id}/lifecycle/activate?sendEmail=true to Okta.
       c. DynamoDB PutItem with the full identity snapshot + outcome.
  4. Post one batch-summary Block Kit message to #joiner-it-ops.
  5. Emit structured JSON to CloudWatch Logs for each user + the final summary.

This is the PROACTIVE half of the JML pipeline. The existing us-east-1
novatech-okta-hook Lambda is the REACTIVE half (per-user posts when each
hire clicks their activation link later in the day).

Secrets are pulled from AWS Secrets Manager (us-west-1 replicas) at module
load and cached for cold-start amortization across reused executions. The
execution role is scoped (in terraform/aws-onboarding/iam.tf) to
GetSecretValue on exactly the 4 replica ARNs and GetItem/PutItem on exactly
the ohmgym-onboarding-logs table.
"""

# DUPLICATED IN: lambdas/okta_activation_handler/handler.py
#   The JWT exchange, secret-cache, Slack post, and channel resolution
#   helpers are intentionally inlined here rather than shared via a Lambda
#   Layer — see public-docs/10-aws-scheduled-onboarding-workflow.md trade-offs.

import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import boto3
import jwt
import requests


SECRETS_REGION = os.environ.get("SECRETS_REGION", "us-west-1")
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_BOT_TOKEN_SECRET_NAME"]
OKTA_API_CLIENT_ID_SECRET_NAME = os.environ["OKTA_API_CLIENT_ID_SECRET_NAME"]
OKTA_API_KEY_ID_SECRET_NAME = os.environ["OKTA_API_KEY_ID_SECRET_NAME"]
OKTA_API_PRIVATE_KEY_SECRET_NAME = os.environ["OKTA_API_PRIVATE_KEY_SECRET_NAME"]
OKTA_ORG_URL = os.environ["OKTA_ORG_URL"].rstrip("/")
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]
DYNAMODB_TTL_DAYS = int(os.environ.get("DYNAMODB_TTL_DAYS", "90"))
SLACK_TEAM_ID = os.environ.get("SLACK_TEAM_ID", "")
JOINER_CHANNEL_NAME = os.environ.get("JOINER_CHANNEL_NAME", "joiner-it-ops")
ACTIVATE_PACE_SECONDS = float(os.environ.get("ACTIVATE_PACE_SECONDS", "0.2"))

_PT = ZoneInfo("America/Los_Angeles")

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=SECRETS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE_NAME)


def _fetch_secret(name: str) -> str:
    return _secrets_client.get_secret_value(SecretId=name)["SecretString"]


_SLACK_BOT_TOKEN = _fetch_secret(SLACK_BOT_TOKEN_SECRET_NAME)
_OKTA_API_CLIENT_ID = _fetch_secret(OKTA_API_CLIENT_ID_SECRET_NAME)
_OKTA_API_PRIVATE_KEY = _fetch_secret(OKTA_API_PRIVATE_KEY_SECRET_NAME)
_OKTA_API_KEY_ID = _fetch_secret(OKTA_API_KEY_ID_SECRET_NAME)

# Cached access token across warm invocations.
_okta_token_cache: dict = {"token": None, "expires_at": 0}


def _today_pt(override: str | None) -> str:
    """Return YYYY-MM-DD in America/Los_Angeles, honoring an override."""
    if override:
        # Validate by round-tripping through fromisoformat — raises on bad input.
        datetime.fromisoformat(override)
        return override
    return datetime.now(_PT).date().isoformat()


def _okta_access_token() -> str:
    """Return a valid Okta API access token, exchanging a JWT if needed."""
    now = int(time.time())
    if _okta_token_cache["token"] and _okta_token_cache["expires_at"] - 60 > now:
        return _okta_token_cache["token"]

    token_url = f"{OKTA_ORG_URL}/oauth2/v1/token"
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
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "client_credentials",
            "scope": "okta.users.read okta.users.manage",
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


def _search_staged_users(today_pt: str) -> list[dict]:
    """Server-side filter Okta users by STAGED + today's startDate."""
    token = _okta_access_token()
    search = f'status eq "STAGED" and profile.startDate eq "{today_pt}"'
    resp = requests.get(
        f"{OKTA_ORG_URL}/api/v1/users",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params={"search": search, "limit": 200},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() or []


def _already_activated_today(run_date: str, user_id: str) -> bool:
    """Idempotency guard. True if a success row already exists for today."""
    resp = _table.get_item(
        Key={"run_date": run_date, "user_id": user_id},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    return bool(item and item.get("status") == "success")


def _activate_user(user_id: str) -> tuple[int, str]:
    """POST to Okta's activate endpoint with sendEmail=true.

    Returns (http_status, error_message_or_empty).
    """
    token = _okta_access_token()
    resp = requests.post(
        f"{OKTA_ORG_URL}/api/v1/users/{user_id}/lifecycle/activate",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        params={"sendEmail": "true"},
        timeout=10,
    )
    if resp.status_code in (200, 204):
        return resp.status_code, ""
    # Okta returns a JSON error body with errorCode + errorSummary on failure.
    try:
        body = resp.json()
        summary = body.get("errorSummary") or body.get("errorCode") or resp.text
    except Exception:
        summary = resp.text
    return resp.status_code, summary[:500]


def _record_attempt(
    *,
    run_date: str,
    batch_run_id: str,
    user: dict,
    status: str,
    okta_response_status: int,
    error_message: str,
) -> None:
    """Write one audit row to ohmgym-onboarding-logs."""
    profile = user.get("profile") or {}
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    ttl_epoch = int((datetime.now(timezone.utc) + timedelta(days=DYNAMODB_TTL_DAYS)).timestamp())
    item = {
        "run_date": run_date,
        "user_id": user["id"],
        "login": profile.get("login", ""),
        "first_name": profile.get("firstName", ""),
        "last_name": profile.get("lastName", ""),
        "department": profile.get("department", ""),
        "role_title": profile.get("role_title", "") or profile.get("title", ""),
        "start_date": profile.get("startDate", ""),
        "status": status,
        "okta_response_status": okta_response_status,
        "error_message": error_message,
        "timestamp_utc": now_utc,
        "batch_run_id": batch_run_id,
        "ttl_epoch": ttl_epoch,
    }
    _table.put_item(Item=item)


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
    """Resolve channel by name, creating it if missing. Returns (ok, id|error)."""
    if not SLACK_TEAM_ID:
        return False, "missing_team_id_env"
    headers = {"Authorization": f"Bearer {_SLACK_BOT_TOKEN}"}

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

    cursor = ""
    while True:
        params = {
            "limit": "200",
            "types": "public_channel",
            "team_id": SLACK_TEAM_ID,
        }
        if cursor:
            params["cursor"] = cursor
        list_resp = requests.get(
            "https://slack.com/api/conversations.list",
            headers=headers,
            params=params,
            timeout=15,
        ).json()
        if not list_resp.get("ok"):
            return False, list_resp.get("error", "list_failed")
        for ch in list_resp.get("channels", []):
            if ch.get("name") == name:
                return True, ch["id"]
        cursor = list_resp.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return False, "channel_not_found"


def _build_batch_summary_blocks(
    run_date: str,
    activated: list[dict],
    errors: list[dict],
    skipped: list[dict],
    batch_run_id: str,
) -> tuple[str, list]:
    """Slack Block Kit shape for the daily summary."""
    n_act = len(activated)
    n_err = len(errors)
    text = f":rocket: Daily joiner activations — {run_date}: {n_act} activated, {n_err} errors"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚀 Daily joiner activations — {run_date}"},
        }
    ]

    if activated:
        lines = [
            f"• {u.get('first_name', '')} {u.get('last_name', '')}".strip()
            + (f" — {u['role_title']}, {u['department']}" if u.get("role_title") or u.get("department") else "")
            + f" ({u.get('login', '')})"
            for u in activated
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Activated ({n_act}):*\n" + "\n".join(lines)},
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Activated (0):*\n_No STAGED users with today's startDate._"},
        })

    if errors:
        err_lines = [f"• `{e.get('login', '?')}` — {e.get('error', '?')}" for e in errors]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Errors ({n_err}):*\n" + "\n".join(err_lines)},
        })

    if skipped:
        skip_lines = [f"• `{s.get('login', '?')}` — {s.get('reason', '?')}" for s in skipped]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Skipped ({len(skipped)}):*\n" + "\n".join(skip_lines)},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"batch_run_id: `{batch_run_id}` • run_date_pt: `{run_date}` • Posted by NovaTech IT Ops automation"},
        ],
    })
    return text, blocks


def _post_batch_summary(
    run_date: str,
    activated: list[dict],
    errors: list[dict],
    skipped: list[dict],
    batch_run_id: str,
) -> dict:
    ok, channel_id = _resolve_or_create_channel(JOINER_CHANNEL_NAME)
    if not ok:
        return {"posted": False, "reason": f"channel:{channel_id}"}
    text, blocks = _build_batch_summary_blocks(run_date, activated, errors, skipped, batch_run_id)
    ok, detail = _post_slack(channel_id, text, blocks)
    if ok:
        return {"posted": True, "channel": channel_id, "ts": detail}
    return {"posted": False, "reason": f"post:{detail}"}


def lambda_handler(event, context):  # noqa: ARG001  (context unused)
    """Entry point. `event` may contain `override_date` for manual replays."""
    batch_run_id = uuid.uuid4().hex
    override = (event or {}).get("override_date")
    run_date = _today_pt(override)

    activated: list[dict] = []
    errors: list[dict] = []
    skipped: list[dict] = []

    try:
        users = _search_staged_users(run_date)
    except requests.HTTPError as e:
        # Hard failure — let Lambda surface the error so the alarm fires.
        print(json.dumps({
            "event": "okta_search_failed",
            "run_date": run_date,
            "batch_run_id": batch_run_id,
            "http_status": getattr(e.response, "status_code", None),
            "error": str(e)[:500],
        }))
        raise

    for user in users:
        profile = user.get("profile") or {}
        login = profile.get("login", "(unknown)")
        user_id = user.get("id", "")
        if not user_id:
            errors.append({"login": login, "error": "missing_user_id"})
            continue

        if _already_activated_today(run_date, user_id):
            skipped.append({"login": login, "user_id": user_id, "reason": "already_activated_today"})
            continue

        http_status, err_msg = _activate_user(user_id)
        if http_status in (200, 204):
            entry = {
                "user_id": user_id,
                "login": login,
                "first_name": profile.get("firstName", ""),
                "last_name": profile.get("lastName", ""),
                "department": profile.get("department", ""),
                "role_title": profile.get("role_title", "") or profile.get("title", ""),
            }
            activated.append(entry)
            _record_attempt(
                run_date=run_date,
                batch_run_id=batch_run_id,
                user=user,
                status="success",
                okta_response_status=http_status,
                error_message="",
            )
        else:
            errors.append({"login": login, "user_id": user_id, "error": err_msg, "http_status": http_status})
            _record_attempt(
                run_date=run_date,
                batch_run_id=batch_run_id,
                user=user,
                status="error",
                okta_response_status=http_status,
                error_message=err_msg,
            )

        if ACTIVATE_PACE_SECONDS > 0:
            time.sleep(ACTIVATE_PACE_SECONDS)

    slack_result = _post_batch_summary(run_date, activated, errors, skipped, batch_run_id)

    summary = {
        "event": "onboarding_batch_complete",
        "run_date": run_date,
        "batch_run_id": batch_run_id,
        "activated_count": len(activated),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "activated": activated,
        "errors": errors,
        "skipped": skipped,
        "slack": slack_result,
    }
    print(json.dumps(summary))
    return summary
