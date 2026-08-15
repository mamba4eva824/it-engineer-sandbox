"""AWS Lambda handler for the ohmgym offboarding workflow.

Invoked by EventBridge Scheduler at 17:00 America/Los_Angeles daily. On each
invocation:

  1. Compute today_pt (overridable via event["override_date"] for replays).
  2. Query Okta Management API for users matching
       status eq "ACTIVE" and profile.endDate eq "<today_pt>"
     via the server-side `search` filter.
  3. For each matched user:
       a. DynamoDB GetItem on (run_date, user_id) — skip if already success.
       b. DELETE /api/v1/users/{id}/sessions (security-critical, before deactivate).
       c. POST /api/v1/users/{id}/lifecycle/deactivate to Okta.
       d. DynamoDB PutItem with the full identity snapshot + outcome.
  4. Post one batch-summary Block Kit message to #leaver-it-ops.
  5. On each successful deactivate, PutEvents leaver.completed for the
     license scanner (failure is logged and does not undo Okta deactivate).
  6. Emit structured JSON to CloudWatch Logs for each user + the final summary.

This is the PROACTIVE leaver half of the JML pipeline. SCIM cascades Slack
(and GWS for real SCIM users) without code in this Lambda.

Secrets are pulled from AWS Secrets Manager (us-west-1 ohmgym-jml/*) at module
load and cached for cold-start amortization across reused executions.
"""

# DUPLICATED IN: lambdas/onboarding_workflow/handler.py, scripts/slack/notify.py
#   JWT exchange, secret-cache, Slack post, and channel resolution helpers.

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
LEAVER_CHANNEL_NAME = os.environ.get("LEAVER_CHANNEL_NAME", "leaver-it-ops")
DEACTIVATE_PACE_SECONDS = float(os.environ.get("DEACTIVATE_PACE_SECONDS", "0.2"))

_PT = ZoneInfo("America/Los_Angeles")

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=SECRETS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE_NAME)
_events = boto3.client("events", region_name=SECRETS_REGION)

LEAVER_COMPLETED_SOURCE = "ohmgym.offboarding"
LEAVER_COMPLETED_DETAIL_TYPE = "leaver.completed"


def _fetch_secret(name: str) -> str:
    return _secrets_client.get_secret_value(SecretId=name)["SecretString"]


_SLACK_BOT_TOKEN = _fetch_secret(SLACK_BOT_TOKEN_SECRET_NAME)
_OKTA_API_CLIENT_ID = _fetch_secret(OKTA_API_CLIENT_ID_SECRET_NAME)
_OKTA_API_PRIVATE_KEY = _fetch_secret(OKTA_API_PRIVATE_KEY_SECRET_NAME)
_OKTA_API_KEY_ID = _fetch_secret(OKTA_API_KEY_ID_SECRET_NAME)

_okta_token_cache: dict = {"token": None, "expires_at": 0}


def _today_pt(override: str | None) -> str:
    if override:
        datetime.fromisoformat(override)
        return override
    return datetime.now(_PT).date().isoformat()


def _okta_access_token() -> str:
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


def _search_active_leavers(today_pt: str) -> list[dict]:
    token = _okta_access_token()
    search = (
        f'(status eq "ACTIVE" or status eq "PROVISIONED") '
        f'and profile.endDate eq "{today_pt}"'
    )
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


def _already_deactivated_today(run_date: str, user_id: str) -> bool:
    resp = _table.get_item(
        Key={"run_date": run_date, "user_id": user_id},
        ConsistentRead=True,
    )
    item = resp.get("Item")
    return bool(item and item.get("status") == "success")


def _revoke_sessions(user_id: str) -> tuple[int, str]:
    token = _okta_access_token()
    resp = requests.delete(
        f"{OKTA_ORG_URL}/api/v1/users/{user_id}/sessions",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=10,
    )
    if resp.status_code in (200, 204):
        return resp.status_code, ""
    if resp.status_code in (403, 404):
        return resp.status_code, ""
    try:
        body = resp.json()
        summary = body.get("errorSummary") or body.get("errorCode") or resp.text
    except Exception:
        summary = resp.text
    return resp.status_code, summary[:500]


def _deactivate_user(user_id: str) -> tuple[int, str]:
    token = _okta_access_token()
    resp = requests.post(
        f"{OKTA_ORG_URL}/api/v1/users/{user_id}/lifecycle/deactivate",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        },
        timeout=30,
    )
    if resp.status_code in (200, 204):
        return resp.status_code, ""
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
        "start_date": profile.get("endDate", ""),
        "status": status,
        "okta_response_status": okta_response_status,
        "error_message": error_message,
        "timestamp_utc": now_utc,
        "batch_run_id": batch_run_id,
        "ttl_epoch": ttl_epoch,
    }
    _table.put_item(Item=item)


def _emit_leaver_completed(
    *,
    user_email: str,
    okta_id: str,
    run_id: str,
    run_date: str,
    github_username: str | None,
    first_name: str = "",
    last_name: str = "",
) -> None:
    """Publish leaver.completed for the license scanner. Raises on failed entries."""
    detail = {
        "user_email": user_email,
        "okta_id": okta_id,
        "run_id": run_id,
        "run_date": run_date,
        "github_username": github_username or None,
        "first_name": first_name or "",
        "last_name": last_name or "",
    }
    resp = _events.put_events(
        Entries=[{
            "Source": LEAVER_COMPLETED_SOURCE,
            "DetailType": LEAVER_COMPLETED_DETAIL_TYPE,
            "Detail": json.dumps(detail),
        }]
    )
    if resp.get("FailedEntryCount", 0):
        entries = resp.get("Entries") or []
        reason = entries[0].get("ErrorMessage", "put_events failed") if entries else "put_events failed"
        raise RuntimeError(reason[:500])


def _post_slack(channel_id: str, text: str, blocks: list) -> tuple[bool, str]:
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
    deactivated: list[dict],
    errors: list[dict],
    skipped: list[dict],
    batch_run_id: str,
) -> tuple[str, list]:
    n_act = len(deactivated)
    n_err = len(errors)
    text = f":no_entry: Daily leaver deactivations — {run_date}: {n_act} deactivated, {n_err} errors"

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚪 Daily leaver deactivations — {run_date}"},
        }
    ]

    if deactivated:
        lines = [
            f"• {u.get('first_name', '')} {u.get('last_name', '')}".strip()
            + (f" — {u['role_title']}, {u['department']}" if u.get("role_title") or u.get("department") else "")
            + f" ({u.get('login', '')})"
            for u in deactivated
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Deactivated ({n_act}):*\n" + "\n".join(lines)},
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Deactivated (0):*\n_No ACTIVE users with today's endDate._"},
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
    deactivated: list[dict],
    errors: list[dict],
    skipped: list[dict],
    batch_run_id: str,
) -> dict:
    ok, channel_id = _resolve_or_create_channel(LEAVER_CHANNEL_NAME)
    if not ok:
        return {"posted": False, "reason": f"channel:{channel_id}"}
    text, blocks = _build_batch_summary_blocks(run_date, deactivated, errors, skipped, batch_run_id)
    ok, detail = _post_slack(channel_id, text, blocks)
    if ok:
        return {"posted": True, "channel": channel_id, "ts": detail}
    return {"posted": False, "reason": f"post:{detail}"}


def lambda_handler(event, context):  # noqa: ARG001
    batch_run_id = uuid.uuid4().hex
    override = (event or {}).get("override_date")
    run_date = _today_pt(override)

    deactivated: list[dict] = []
    errors: list[dict] = []
    skipped: list[dict] = []

    try:
        users = _search_active_leavers(run_date)
    except requests.HTTPError as e:
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

        if _already_deactivated_today(run_date, user_id):
            skipped.append({"login": login, "user_id": user_id, "reason": "already_deactivated_today"})
            continue

        sess_status, sess_err = _revoke_sessions(user_id)
        if sess_status not in (200, 204, 403, 404):
            errors.append({
                "login": login,
                "user_id": user_id,
                "error": f"session_revoke: {sess_err}",
                "http_status": sess_status,
            })
            _record_attempt(
                run_date=run_date,
                batch_run_id=batch_run_id,
                user=user,
                status="error",
                okta_response_status=sess_status,
                error_message=f"session_revoke: {sess_err}",
            )
            continue

        http_status, err_msg = _deactivate_user(user_id)
        if http_status in (200, 204):
            entry = {
                "user_id": user_id,
                "login": login,
                "first_name": profile.get("firstName", ""),
                "last_name": profile.get("lastName", ""),
                "department": profile.get("department", ""),
                "role_title": profile.get("role_title", "") or profile.get("title", ""),
            }
            deactivated.append(entry)
            _record_attempt(
                run_date=run_date,
                batch_run_id=batch_run_id,
                user=user,
                status="success",
                okta_response_status=http_status,
                error_message="",
            )
            github_username = (profile.get("githubUsername") or "").strip() or None
            try:
                _emit_leaver_completed(
                    user_email=login,
                    okta_id=user_id,
                    run_id=batch_run_id,
                    run_date=run_date,
                    github_username=github_username,
                    first_name=profile.get("firstName", ""),
                    last_name=profile.get("lastName", ""),
                )
            except Exception as e:
                print(json.dumps({
                    "event": "leaver_completed_emit_failed",
                    "run_date": run_date,
                    "batch_run_id": batch_run_id,
                    "okta_id": user_id,
                    "login": login,
                    "error": str(e)[:500],
                }))
                errors.append({
                    "login": login,
                    "user_id": user_id,
                    "error": f"leaver_completed_emit: {e}"[:500],
                })
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

        if DEACTIVATE_PACE_SECONDS > 0:
            time.sleep(DEACTIVATE_PACE_SECONDS)

    slack_result = _post_batch_summary(run_date, deactivated, errors, skipped, batch_run_id)

    summary = {
        "event": "offboarding_batch_complete",
        "run_date": run_date,
        "batch_run_id": batch_run_id,
        "deactivated_count": len(deactivated),
        "error_count": len(errors),
        "skipped_count": len(skipped),
        "deactivated": deactivated,
        "errors": errors,
        "skipped": skipped,
        "slack": slack_result,
    }
    print(json.dumps(summary))
    return summary
