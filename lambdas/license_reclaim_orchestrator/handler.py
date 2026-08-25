"""AWS Lambda handler for the ohmgym license reclaim orchestrator (Phase 5).

Invoked by EventBridge on license.scan.complete (when the target is enabled)
or directly via scripts/licenses/orchestrate.py. This Lambda never holds SaaS
write credentials (ADR-005): it plans with GPT-5.6 Luna via the OpenAI API, then POSTs the
existing reclaim broker Function URL.

Loop (mirrors the HITL skill, minus the chat gate):

  1. Load findings by issue_key. Refuse SUP-2 and missing rows.
  2. Re-read JSM reclaim fields customfield_10138–10142.
  3. Candidate set = enabled allowlist apps whose scan status is active.
  4. OpenAI Responses API + submit_reclaim_plan tool. Capture usage tokens.
  5. Policy intersect (fixture, hold keywords, allowlist, scan-active only).
  6. If any reclaim[]: dry-run broker, then live POST.
  7. Jira comment (outcomes + token counts). After a live reclaim succeeds
     with no leftover holds, walk the JSM workflow to Done (Start then Resolved).
  8. Slack #leaver-it-ops. Raise on infra / broker 5xx — never on a model hold.

ORCHESTRATOR_AUTO_RUN: EventBridge license.scan.complete no-ops when this is
false. CLI invokes always run.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import boto3
import requests
_HERE = Path(__file__).resolve().parent
_SCRIPTS_LICENSES = _HERE.parent.parent / "scripts" / "licenses"
if _SCRIPTS_LICENSES.is_dir():
    sys.path.insert(0, str(_SCRIPTS_LICENSES))

from jira_client import (  # noqa: E402
    add_comment,
    get_issue,
    list_transitions,
    transition_issue,
    transition_to_done,
)

from policy import (  # noqa: E402
    FIXTURE_ISSUE_KEY,
    ReclaimPlan,
    candidate_apps,
    empty_plan,
    hold_apps,
    hold_notes_blocked,
    intersect_plan,
    notes_text,
    normalize_plan,
    parse_app_list,
    reclaim_apps,
)

SECRETS_REGION = os.environ.get("SECRETS_REGION", "us-west-1")
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_BOT_TOKEN_SECRET_NAME"]
JIRA_READ_SECRET_NAME = os.environ["JIRA_READ_SECRET_NAME"]
WEBHOOK_SECRET_NAME = os.environ["WEBHOOK_SECRET_NAME"]
BROKER_FUNCTION_URL = os.environ.get("BROKER_FUNCTION_URL", "")
JIRA_CLOUD_ID = os.environ.get("JIRA_CLOUD_ID", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]
DYNAMODB_ISSUE_KEY_INDEX = os.environ.get("DYNAMODB_ISSUE_KEY_INDEX", "jira_issue_key-index")
SLACK_TEAM_ID = os.environ.get("SLACK_TEAM_ID", "")
LEAVER_CHANNEL_NAME = os.environ.get("LEAVER_CHANNEL_NAME", "leaver-it-ops")
OPENAI_SECRET_NAME = os.environ.get("OPENAI_SECRET_NAME", "ohmgym-licenses/openai")
OPENAI_MODEL_ID = os.environ.get("OPENAI_MODEL_ID", "gpt-5.6-luna")
OPENAI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
OPENAI_MAX_TOKENS = int(os.environ.get("OPENAI_MAX_TOKENS", "2048"))
REQUESTED_BY = os.environ.get("ORCHESTRATOR_REQUESTED_BY", "orchestrator@ohmgym.com")
ORCHESTRATOR_AUTO_RUN = os.environ.get("ORCHESTRATOR_AUTO_RUN", "true")

SCAN_COMPLETE_SOURCE = "ohmgym.licenses"
SCAN_COMPLETE_DETAIL_TYPE = "license.scan.complete"
SUBMIT_TOOL = "submit_reclaim_plan"

CF_LEAVER_EMAIL = "customfield_10138"
CF_OKTA_USER_ID = "customfield_10139"
CF_OFFBOARDING_RUN_ID = "customfield_10140"
CF_APPS = "customfield_10141"
CF_NOTES = "customfield_10142"
JIRA_RECLAIM_FIELDS = ",".join(
    [
        "summary",
        "status",
        "description",
        CF_LEAVER_EMAIL,
        CF_OKTA_USER_ID,
        CF_OFFBOARDING_RUN_ID,
        CF_APPS,
        CF_NOTES,
    ]
)

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=SECRETS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE_NAME)


def _fetch_secret(name: str) -> str:
    return _secrets_client.get_secret_value(SecretId=name)["SecretString"]


def _parse_openai_api_key(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        raise ValueError("openai secret is empty")
    if text.startswith("{"):
        data = json.loads(text)
        for key in ("api_key", "openai_api_key", "OPENAI_API_KEY", "key", "token"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        raise ValueError("openai secret JSON missing api_key")
    return text


_SLACK_BOT_TOKEN = _fetch_secret(SLACK_BOT_TOKEN_SECRET_NAME)
_JIRA_API_TOKEN = _fetch_secret(JIRA_READ_SECRET_NAME)
_WEBHOOK_SECRET = _fetch_secret(WEBHOOK_SECRET_NAME)
_OPENAI_API_KEY = _parse_openai_api_key(_fetch_secret(OPENAI_SECRET_NAME))


def _load_apps_config() -> dict[str, Any]:
    candidates = [
        _HERE / "config" / "licenses" / "apps.json",
        _HERE.parent.parent / "config" / "licenses" / "apps.json",
    ]
    for path in candidates:
        if path.is_file():
            return json.loads(path.read_text())
    raise FileNotFoundError("config/licenses/apps.json not found")


def _log(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, default=str))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _auto_run_enabled() -> bool:
    return ORCHESTRATOR_AUTO_RUN.strip().lower() not in ("0", "false", "no", "off")


def _is_eventbridge_scan_complete(event: dict[str, Any]) -> bool:
    return event.get("detail-type") == SCAN_COMPLETE_DETAIL_TYPE or (
        event.get("source") == SCAN_COMPLETE_SOURCE and event.get("detail") is not None
    )


def _unwrap_event(event: dict[str, Any] | None) -> tuple[dict[str, Any], bool, bool]:
    """Return (detail, dry_run, from_eventbridge)."""
    if not event:
        raise ValueError("empty orchestrator payload")
    if _is_eventbridge_scan_complete(event):
        detail = event.get("detail")
        if isinstance(detail, str):
            detail = json.loads(detail)
        detail = detail or {}
        dry_run = bool(event.get("dry_run") or detail.get("dry_run"))
        return detail, dry_run, True
    return event, bool(event.get("dry_run")), False


def query_by_issue_key(issue_key: str) -> dict[str, Any] | None:
    resp = _table.query(
        IndexName=DYNAMODB_ISSUE_KEY_INDEX,
        KeyConditionExpression="jira_issue_key = :k",
        ExpressionAttributeValues={":k": issue_key},
        Limit=1,
    )
    items = resp.get("Items") or []
    return items[0] if items else None


def _to_ddb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def persist_planner(row: dict[str, Any], planner: dict[str, Any]) -> None:
    _table.update_item(
        Key={"run_date": row["run_date"], "user_id": row["user_id"]},
        UpdateExpression="SET planner = :p",
        ExpressionAttributeValues={":p": _to_ddb(planner)},
    )


def parse_usage(response: dict[str, Any], *, latency_ms: int | None = None) -> tuple[dict[str, Any], bool]:
    usage = response.get("usage")
    empty = {
        "model_id": OPENAI_MODEL_ID,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "latency_ms": latency_ms,
    }
    if not isinstance(usage, dict):
        return empty, True
    prompt = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total = int(usage.get("total_tokens") or (prompt + completion))
    details = {}
    if isinstance(usage.get("prompt_tokens_details"), dict):
        details = usage["prompt_tokens_details"]
    elif isinstance(usage.get("input_tokens_details"), dict):
        details = usage["input_tokens_details"]
    cached = int(details.get("cached_tokens") or 0)
    return {
        "model_id": str(response.get("model") or OPENAI_MODEL_ID),
        "input_tokens": prompt,
        "output_tokens": completion,
        "total_tokens": total,
        "cache_read_input_tokens": cached,
        "cache_write_input_tokens": 0,
        "latency_ms": latency_ms,
    }, False


def _plan_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["issue_key", "user_email", "decisions", "confidence"],
        "additionalProperties": False,
        "properties": {
            "issue_key": {"type": "string"},
            "user_email": {"type": "string"},
            "confidence": {"type": "number"},
            "decisions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["app", "action", "reason"],
                    "additionalProperties": False,
                    "properties": {
                        "app": {"type": "string"},
                        "action": {
                            "type": "string",
                            "enum": ["reclaim", "skip", "hold"],
                        },
                        "reason": {"type": "string"},
                    },
                },
            },
        },
    }


def _openai_tools() -> list[dict[str, Any]]:
    # Responses API function tools are flat (name/parameters), not Chat Completions nested.
    return [
        {
            "type": "function",
            "name": SUBMIT_TOOL,
            "description": (
                "Submit the reclaim/skip/hold plan for candidate apps only. "
                "Do not invent users or app keys."
            ),
            "parameters": _plan_schema(),
            "strict": False,
        }
    ]


def _extract_tool_input(response: dict[str, Any]) -> Any:
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        if item.get("type") != "function_call":
            continue
        if item.get("name") != SUBMIT_TOOL:
            continue
        raw = item.get("arguments")
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (TypeError, ValueError):
                continue
    for choice in response.get("choices") or []:
        message = (choice or {}).get("message") or {}
        for call in message.get("tool_calls") or []:
            fn = call.get("function") or {}
            if fn.get("name") != SUBMIT_TOOL:
                continue
            raw = fn.get("arguments")
            if isinstance(raw, dict):
                return raw
            if isinstance(raw, str) and raw.strip():
                try:
                    return json.loads(raw)
                except (TypeError, ValueError):
                    continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            try:
                return json.loads(content)
            except (TypeError, ValueError):
                continue
    return None


def openai_plan(
    *,
    issue_key: str,
    user_email: str,
    notes: str,
    candidates: list[str],
    findings: list[dict[str, Any]],
    apps_config: dict[str, Any],
) -> tuple[ReclaimPlan, dict[str, Any], bool, str | None]:
    hints = {
        app: bool((apps_config.get(app) or {}).get("auto_reclaim"))
        for app in candidates
    }
    candidate_findings = [f for f in findings if f.get("app") in candidates]
    system = (
        "You are NovaTech license-reclaim planner. Decide reclaim, skip, or hold "
        "only for the candidate apps. Never invent users or app keys. Default to "
        "hold when uncertain. auto_reclaim is a hint (prefer reclaim when notes "
        "are empty), not a bypass. Call submit_reclaim_plan."
    )
    user_text = json.dumps(
        {
            "issue_key": issue_key,
            "user_email": user_email,
            "hold_notes": notes,
            "candidates": candidates,
            "auto_reclaim_hints": hints,
            "findings": candidate_findings,
        },
        default=str,
    )
    payload = {
        "model": OPENAI_MODEL_ID,
        "instructions": system,
        "input": user_text,
        "tools": _openai_tools(),
        "tool_choice": {"type": "function", "name": SUBMIT_TOOL},
        "max_output_tokens": OPENAI_MAX_TOKENS,
        "reasoning": {"effort": "low"},
        "store": False,
    }
    started = time.perf_counter()
    try:
        resp = requests.post(
            f"{OPENAI_BASE_URL}/responses",
            headers={
                "Authorization": f"Bearer {_OPENAI_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=45,
        )
        if resp.status_code >= 400:
            body = (resp.text or "")[:500]
            raise requests.HTTPError(
                f"{resp.status_code} Client Error: {body}",
                response=resp,
            )
        resp.raise_for_status()
        response = resp.json()
    except (requests.Timeout, requests.ConnectionError, TimeoutError, requests.RequestException) as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        usage, _ = parse_usage({}, latency_ms=latency_ms)
        return empty_plan(issue_key, user_email, reason="openai_timeout"), usage, True, str(exc)[:500]

    latency_ms = int((time.perf_counter() - started) * 1000)
    usage, usage_missing = parse_usage(response if isinstance(response, dict) else {}, latency_ms=latency_ms)
    raw = _extract_tool_input(response if isinstance(response, dict) else {})
    if raw is None:
        plan = empty_plan(issue_key, user_email, reason="no_tool_use")
        for app in candidates:
            plan["decisions"].append(
                {"app": app, "action": "hold", "reason": "model returned no tool call; default hold"}
            )
        return plan, usage, usage_missing, None
    return normalize_plan(raw, issue_key=issue_key, user_email=user_email), usage, usage_missing, None


def _jira_field(fields: dict[str, Any], field_id: str) -> Any:
    value = fields.get(field_id)
    if isinstance(value, dict) and "value" in value:
        return value.get("value")
    return value


def read_ticket(issue_key: str) -> dict[str, Any]:
    status, body = get_issue(
        cloud_id=JIRA_CLOUD_ID,
        auth_email=JIRA_EMAIL,
        token=_JIRA_API_TOKEN,
        issue_key=issue_key,
        fields=JIRA_RECLAIM_FIELDS,
    )
    if status != 200:
        raise RuntimeError(f"JSM get_issue failed HTTP {status}")
    fields = body.get("fields") or {}
    return {
        "issue_key": issue_key,
        "user_email": str(_jira_field(fields, CF_LEAVER_EMAIL) or "").strip(),
        "okta_user_id": str(_jira_field(fields, CF_OKTA_USER_ID) or "").strip(),
        "offboarding_run_id": str(_jira_field(fields, CF_OFFBOARDING_RUN_ID) or "").strip(),
        "apps": parse_app_list(_jira_field(fields, CF_APPS)),
        "notes": notes_text(_jira_field(fields, CF_NOTES)),
        "status": ((fields.get("status") or {}).get("name") or ""),
    }


def post_broker(*, issue_key: str, apps: list[str], dry_run: bool) -> dict[str, Any]:
    if not BROKER_FUNCTION_URL:
        raise RuntimeError("BROKER_FUNCTION_URL is not set")
    payload = {
        "issue_key": issue_key,
        "requested_by": REQUESTED_BY,
        "apps": apps,
        "dry_run": dry_run,
    }
    resp = requests.post(
        BROKER_FUNCTION_URL,
        headers={
            "Authorization": _WEBHOOK_SECRET,
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": (resp.text or "")[:500]}
    if resp.status_code >= 500:
        raise RuntimeError(f"broker HTTP {resp.status_code}: {body}")
    if resp.status_code >= 400:
        return {"ok": False, "http_status": resp.status_code, "body": body, "dry_run": dry_run}
    return {"ok": True, "http_status": resp.status_code, "body": body, "dry_run": dry_run}


def _broker_app_succeeded(result: dict[str, Any]) -> bool:
    status = str(result.get("status") or result.get("outcome") or "").lower()
    return status in ("reclaimed", "already_reclaimed", "success")


def _comment_ticket(issue_key: str, text: str) -> None:
    try:
        add_comment(
            cloud_id=JIRA_CLOUD_ID,
            auth_email=JIRA_EMAIL,
            token=_JIRA_API_TOKEN,
            issue_key=issue_key,
            text=text,
        )
    except Exception as exc:  # best-effort; never raises (mirrors scanner Slack)
        _log({
            "event": "orchestrator_comment_failed",
            "issue_key": issue_key,
            "error_class": "work_queue",
            "error": str(exc)[:500],
        })


def maybe_transition_done(issue_key: str) -> bool:
    """Walk To Do → Start → Resolved/Done. JSM request types have no direct Done hop."""
    ok = transition_to_done(
        cloud_id=JIRA_CLOUD_ID,
        auth_email=JIRA_EMAIL,
        token=_JIRA_API_TOKEN,
        issue_key=issue_key,
    )
    if not ok:
        _log({
            "event": "orchestrator_transition_failed",
            "issue_key": issue_key,
            "error_class": "work_queue",
            "error": "could not reach Done",
        })
    return ok


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
        params = {"limit": "200", "types": "public_channel", "team_id": SLACK_TEAM_ID}
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


def slack_summary(
    *,
    issue_key: str,
    user_email: str,
    plan: ReclaimPlan,
    usage: dict[str, Any],
    broker: dict[str, Any] | None,
    done: bool,
) -> dict[str, Any]:
    decisions = plan.get("decisions") or []
    lines = [f"• `{d['app']}` — {d['action']} — {d.get('reason') or ''}" for d in decisions]
    text = f":robot_face: License orchestrator {issue_key} — {user_email}"
    summary = (
        f"*Leaver:* `{user_email}`\n"
        f"*Ticket:* `{issue_key}`\n"
        f"*Done:* `{done}`\n"
        f"*Tokens:* in `{usage.get('input_tokens')}` / out `{usage.get('output_tokens')}` "
        f"/ total `{usage.get('total_tokens')}` ({usage.get('latency_ms')} ms)"
    )
    if broker:
        summary += f"\n*Broker:* HTTP `{broker.get('http_status')}` dry_run=`{broker.get('dry_run')}`"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"License orchestrator — {issue_key}"},
        },
        {"type": "section", "text": {"type": "mrkdwn", "text": summary}},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Plan:*\n" + ("\n".join(lines) or "_none_")},
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"requested_by: `{REQUESTED_BY}` • Posted by NovaTech IT Ops automation",
            }],
        },
    ]
    ok, channel_id = _resolve_or_create_channel(LEAVER_CHANNEL_NAME)
    if not ok:
        return {"posted": False, "reason": f"channel:{channel_id}"}
    posted, detail = _post_slack(channel_id, text, blocks)
    if posted:
        return {"posted": True, "channel": channel_id, "ts": detail}
    return {"posted": False, "reason": f"post:{detail}"}


def _usage_comment_line(usage: dict[str, Any]) -> str:
    model = usage.get("model_id") or OPENAI_MODEL_ID
    latency = usage.get("latency_ms")
    latency_bit = f" ({latency} ms)" if latency is not None else ""
    return (
        f"OpenAI {model}: {usage.get('input_tokens', 0)} in / "
        f"{usage.get('output_tokens', 0)} out / {usage.get('total_tokens', 0)} total"
        f"{latency_bit}."
    )


def _comment_body(
    *,
    plan: ReclaimPlan,
    usage: dict[str, Any],
    broker_results: list[dict[str, Any]] | None,
    deferred: str | None,
) -> str:
    lines = [
        f"License orchestrator plan for {plan['user_email']} (requested_by={REQUESTED_BY}).",
        _usage_comment_line(usage),
    ]
    for decision in plan.get("decisions") or []:
        lines.append(f"- {decision['app']}: {decision['action']} — {decision.get('reason') or ''}")
    if broker_results:
        lines.append("Broker:")
        for item in broker_results:
            outcome = item.get("status") or item.get("outcome") or item.get("error") or "unknown"
            lines.append(f"- {item.get('app')}: {outcome}")
    if deferred:
        lines.append(f"orchestrator deferred: {deferred}")
    return "\n".join(lines)


def lambda_handler(event, context):  # noqa: ARG001
    try:
        detail, dry_run, from_eventbridge = _unwrap_event(event)
    except Exception as exc:
        _log({
            "event": "reclaim_plan",
            "error_class": "infra",
            "retryable": False,
            "error": str(exc)[:500],
        })
        raise

    if from_eventbridge and not _auto_run_enabled():
        skipped = {
            "event": "reclaim_plan",
            "skipped": True,
            "reason": "ORCHESTRATOR_AUTO_RUN is false",
            "source": SCAN_COMPLETE_SOURCE,
        }
        _log(skipped)
        return skipped

    issue_key = str(detail.get("issue_key") or "").strip()
    if not issue_key:
        raise ValueError("issue_key is required")

    if issue_key == FIXTURE_ISSUE_KEY:
        refused = {
            "event": "reclaim_plan",
            "issue_key": issue_key,
            "error_class": "fixture",
            "refused": True,
            "error": "fixture ticket; orchestrator refuses reclaim",
        }
        _log(refused)
        return refused

    row = query_by_issue_key(issue_key)
    if not row:
        _log({
            "event": "reclaim_plan",
            "issue_key": issue_key,
            "error_class": "not_found",
            "error": "no findings row for issue_key",
        })
        raise RuntimeError(f"no findings for issue_key {issue_key}")

    user_email = str(row.get("login") or "").strip()
    findings = list(row.get("apps") or row.get("apps") or [])
    correlation_id = row.get("correlation_id") or f"JIRA-{issue_key}"

    ticket = read_ticket(issue_key)
    if ticket["user_email"] and user_email and ticket["user_email"].lower() != user_email.lower():
        _log({
            "event": "reclaim_plan",
            "issue_key": issue_key,
            "error_class": "identity",
            "error": "ticket leaver email does not match findings login",
            "correlation_id": correlation_id,
        })
        raise RuntimeError("ticket leaver email does not match findings login")
    user_email = ticket["user_email"] or user_email

    apps_config = _load_apps_config()
    candidates = candidate_apps(
        apps_config=apps_config,
        findings=findings,
        ticket_apps=ticket["apps"],
    )
    notes = ticket["notes"]

    plan, usage, usage_missing, openai_error = openai_plan(
        issue_key=issue_key,
        user_email=user_email,
        notes=notes,
        candidates=candidates,
        findings=findings,
        apps_config=apps_config,
    )
    if openai_error:
        _comment_ticket(issue_key, f"orchestrator deferred: {openai_error}")
        _log({
            "event": "reclaim_plan",
            "issue_key": issue_key,
            "error_class": "infra",
            "retryable": True,
            "error": openai_error,
            "correlation_id": correlation_id,
            **usage,
            "usage_missing": True,
            "stop_reason": "openai_timeout",
        })
        raise RuntimeError(f"openai timeout: {openai_error}")

    plan = intersect_plan(
        plan,
        issue_key=issue_key,
        user_email=user_email,
        candidates=candidates,
        ticket_apps=ticket["apps"],
        notes=notes,
    )
    to_reclaim = reclaim_apps(plan)
    remaining_hold = hold_apps(plan)

    planner = {
        **usage,
        "planned_at": _now_iso(),
        "plan": plan,
        "candidates": candidates,
        "stop_reason": "tool_use",
        "hold_notes_blocked": hold_notes_blocked(notes),
    }
    persist_planner(row, planner)

    plan_log = {
        "event": "reclaim_plan",
        "issue_key": issue_key,
        "correlation_id": correlation_id,
        "login": user_email,
        "dry_run": dry_run,
        "candidates": candidates,
        "plan": plan,
        "model_id": usage["model_id"],
        "input_tokens": usage["input_tokens"],
        "output_tokens": usage["output_tokens"],
        "total_tokens": usage["total_tokens"],
        "cache_read_input_tokens": usage["cache_read_input_tokens"],
        "cache_write_input_tokens": usage["cache_write_input_tokens"],
        "latency_ms": usage["latency_ms"],
        "stop_reason": "tool_use",
    }
    if usage_missing:
        plan_log["usage_missing"] = True
    _log(plan_log)

    broker_dry = None
    broker_live = None
    broker_results: list[dict[str, Any]] = []
    reclaim_ok = True
    if to_reclaim:
        broker_dry = post_broker(issue_key=issue_key, apps=to_reclaim, dry_run=True)
        if not broker_dry.get("ok"):
            raise RuntimeError(f"broker dry-run failed: {broker_dry}")
        if not dry_run:
            broker_live = post_broker(issue_key=issue_key, apps=to_reclaim, dry_run=False)
            if not broker_live.get("ok"):
                raise RuntimeError(f"broker live POST failed: {broker_live}")
            broker_results = list((broker_live.get("body") or {}).get("results") or [])
            succeeded = {
                r.get("app") for r in broker_results if _broker_app_succeeded(r)
            }
            reclaim_ok = all(app in succeeded for app in to_reclaim)

    done = False
    if not dry_run and reclaim_ok and not remaining_hold and to_reclaim:
        done = maybe_transition_done(issue_key)

    comment = _comment_body(
        plan=plan,
        usage=usage,
        broker_results=broker_results or None,
        deferred=None,
    )
    _comment_ticket(issue_key, comment)

    slack = slack_summary(
        issue_key=issue_key,
        user_email=user_email,
        plan=plan,
        usage=usage,
        broker=broker_live or broker_dry,
        done=done,
    )

    result = {
        **plan_log,
        "event": "reclaim_plan",
        "reclaim_apps": to_reclaim,
        "hold_apps": remaining_hold,
        "broker_dry_run": broker_dry,
        "broker_live": broker_live,
        "done": done,
        "slack": slack,
        "usage": usage,
        "usage_missing": usage_missing,
        "planner": planner,
    }
    _log({**result, "event": "reclaim_plan_complete"})
    return result
