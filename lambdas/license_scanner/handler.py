"""AWS Lambda handler for the ohmgym license scanner.

Invoked by EventBridge on leaver.completed (or directly / via scan_cli).
Error handling is a first-class contract (ADR-010 / ADR-011):

  1. Validate the event. Invalid payload → error_class=infra, raise.
  2. GetItem(run_date, user_id) for ticket reuse.
  3. Scan enabled apps independently (one exception cannot skip the others).
  4. Always PutItem findings (best-effort persist before any raise).
  5. Ticket when any enabled app is active OR error; reuse existing issue.
  6. Slack #leaver-it-ops on every run; Slack failure does not raise.
  7. Raise only on infra, JSM create failure after persist, or all connectors failed.

dry_run: run connectors and return the plan; skip JSM, DynamoDB, and Slack.

Read secrets are loaded at import (cold-start crash → Lambda Errors → SNS).
Write secrets are never fetched.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import boto3
import requests

_HERE = Path(__file__).resolve().parent
_SCRIPTS_LICENSES = _HERE.parent.parent / "scripts" / "licenses"
if _SCRIPTS_LICENSES.is_dir():
    sys.path.insert(0, str(_SCRIPTS_LICENSES))

from github_client import scan_github  # noqa: E402
from jira_client import (  # noqa: E402
    add_comment,
    adf_doc,
    create_issue,
    scan_jira,
    search_issues,
    update_issue,
)
from linear_client import DEFAULT_ORG_UUID, scan_linear  # noqa: E402
from row_status import (  # noqa: E402
    NO_LICENSES_TO_RECLAIM,
    compute_scan_row_status,
)

SECRETS_REGION = os.environ.get("SECRETS_REGION", "us-west-1")
SLACK_BOT_TOKEN_SECRET_NAME = os.environ["SLACK_BOT_TOKEN_SECRET_NAME"]
GITHUB_READ_SECRET_NAME = os.environ["GITHUB_READ_SECRET_NAME"]
LINEAR_READ_SECRET_NAME = os.environ["LINEAR_READ_SECRET_NAME"]
JIRA_READ_SECRET_NAME = os.environ["JIRA_READ_SECRET_NAME"]
GITHUB_ORG = os.environ.get("GITHUB_ORG", "ohmgym-sandbox")
JIRA_CLOUD_ID = os.environ.get("JIRA_CLOUD_ID", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
JIRA_PROJECT_KEY = os.environ.get("JIRA_PROJECT_KEY", "SUP")
JIRA_REQUEST_TYPE_ID = os.environ.get("JIRA_REQUEST_TYPE_ID", "4")
JIRA_ISSUE_TYPE_ID = os.environ.get("JIRA_ISSUE_TYPE_ID", "10079")
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]
DYNAMODB_TTL_DAYS = int(os.environ.get("DYNAMODB_TTL_DAYS", "90"))
SLACK_TEAM_ID = os.environ.get("SLACK_TEAM_ID", "")
LEAVER_CHANNEL_NAME = os.environ.get("LEAVER_CHANNEL_NAME", "leaver-it-ops")
LINEAR_ORG_UUID = os.environ.get("LINEAR_ORG_UUID", DEFAULT_ORG_UUID)

CF_REQUEST_TYPE = "customfield_10010"
CF_LEAVER_EMAIL = "customfield_10138"
CF_OKTA_USER_ID = "customfield_10139"
CF_OFFBOARDING_RUN_ID = "customfield_10140"
CF_APPS = "customfield_10141"
CF_NOTES = "customfield_10142"

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=SECRETS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE_NAME)


def _fetch_secret(name: str) -> str:
    return _secrets_client.get_secret_value(SecretId=name)["SecretString"]


_SLACK_BOT_TOKEN = _fetch_secret(SLACK_BOT_TOKEN_SECRET_NAME)
_GITHUB_READ_TOKEN = _fetch_secret(GITHUB_READ_SECRET_NAME)
_LINEAR_API_KEY = _fetch_secret(LINEAR_READ_SECRET_NAME)
_JIRA_API_TOKEN = _fetch_secret(JIRA_READ_SECRET_NAME)


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
    print(json.dumps(payload))


def _unwrap_event(event: dict[str, Any] | None) -> tuple[dict[str, Any], bool]:
    if not event:
        raise ValueError("empty leaver.completed payload")
    detail = event.get("detail") if isinstance(event.get("detail"), (dict, str)) else None
    if event.get("detail-type") == "leaver.completed" or (
        event.get("source") == "ohmgym.offboarding" and detail is not None
    ):
        if isinstance(detail, str):
            detail = json.loads(detail)
        dry_run = bool(event.get("dry_run") or (detail or {}).get("dry_run"))
        return detail or {}, dry_run
    return event, bool(event.get("dry_run"))


def _validate_payload(detail: dict[str, Any]) -> dict[str, str]:
    required = ("user_email", "okta_id", "run_id", "run_date")
    missing = [k for k in required if not str(detail.get(k) or "").strip()]
    if missing:
        raise ValueError(f"invalid leaver.completed payload; missing {missing}")
    github_username = detail.get("github_username")
    if isinstance(github_username, str):
        github_username = github_username.strip() or None
    else:
        github_username = None
    return {
        "user_email": str(detail["user_email"]).strip(),
        "okta_id": str(detail["okta_id"]).strip(),
        "run_id": str(detail["run_id"]).strip(),
        "run_date": str(detail["run_date"]).strip(),
        "github_username": github_username,
        # Optional: absent on payloads from before this field existed (or
        # hand-built dry-run/CLI events) — never required.
        "first_name": str(detail.get("first_name") or "").strip(),
        "last_name": str(detail.get("last_name") or "").strip(),
    }


def _scan_one(app_key: str, spec: dict[str, Any], payload: dict[str, str]) -> dict[str, Any]:
    if not spec.get("enabled"):
        return {
            "app": app_key,
            "status": "skipped",
            "seat_type": None,
            "action_hint": None,
            "error_class": None,
            "http_status": None,
            "retryable": False,
            "error": spec.get("parked_reason"),
        }
    if app_key == "github":
        return scan_github(
            org=GITHUB_ORG,
            token=_GITHUB_READ_TOKEN,
            login=payload.get("github_username"),
        )
    if app_key == "linear":
        return scan_linear(
            api_key=_LINEAR_API_KEY,
            email=payload["user_email"],
            expected_org_uuid=LINEAR_ORG_UUID,
        )
    if app_key == "jira":
        return scan_jira(
            email=payload["user_email"],
            token=_JIRA_API_TOKEN,
            auth_email=JIRA_EMAIL,
            cloud_id=JIRA_CLOUD_ID,
        )
    return {
        "app": app_key,
        "status": "skipped",
        "seat_type": None,
        "action_hint": None,
        "error_class": None,
        "http_status": None,
        "retryable": False,
        "error": f"unknown app {app_key}",
    }


def scan_enabled_apps(payload: dict[str, str], apps_config: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for app_key, spec in apps_config.items():
        try:
            result = _scan_one(app_key, spec, payload)
        except Exception as exc:
            _log({
                "event": "connector_error",
                "app": app_key,
                "okta_id": payload.get("okta_id"),
                "login": payload.get("user_email"),
                "run_id": payload.get("run_id"),
                "run_date": payload.get("run_date"),
                "error_class": "retryable",
                "retryable": True,
                "error": str(exc)[:500],
            })
            result = {
                "app": app_key,
                "status": "error",
                "seat_type": None,
                "action_hint": None,
                "error_class": "retryable",
                "http_status": None,
                "retryable": True,
                "error": str(exc)[:500],
            }
        if result.get("status") == "error":
            _log({
                "event": "connector_error",
                "app": app_key,
                "okta_id": payload.get("okta_id"),
                "login": payload.get("user_email"),
                "run_id": payload.get("run_id"),
                "run_date": payload.get("run_date"),
                "correlation_id": f"OFFBOARD-{payload.get('run_id')}",
                "error_class": result.get("error_class"),
                "http_status": result.get("http_status"),
                "retryable": result.get("retryable"),
                "error": result.get("error"),
            })
        findings.append(result)
    return findings


def _enabled(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in findings if a.get("status") != "skipped"]


def compute_row_status(findings: list[dict[str, Any]]) -> tuple[str, str | None]:
    return compute_scan_row_status(findings)


def needs_ticket(findings: list[dict[str, Any]]) -> bool:
    enabled = _enabled(findings)
    return any(a.get("status") in ("active", "error") for a in enabled)


def active_app_keys(findings: list[dict[str, Any]]) -> list[str]:
    return [a["app"] for a in _enabled(findings) if a.get("status") == "active"]


def error_notes(findings: list[dict[str, Any]]) -> str:
    parts = []
    for app in _enabled(findings):
        if app.get("status") == "error":
            klass = app.get("error_class") or "error"
            msg = app.get("error") or ""
            parts.append(f"{app['app']}: {klass}" + (f" — {msg}" if msg else ""))
    return "; ".join(parts)[:255]


def _identity_apps(findings: list[dict[str, Any]]) -> list[str]:
    return [
        a["app"] for a in _enabled(findings)
        if a.get("error_class") == "identity_unresolved"
    ]


def _connector_error_apps(findings: list[dict[str, Any]]) -> list[str]:
    return [
        a["app"] for a in _enabled(findings)
        if a.get("status") == "error" and a.get("error_class") != "identity_unresolved"
    ]


def _format_app_line(app: dict[str, Any]) -> str:
    if app.get("error_class") == "identity_unresolved":
        detail = app.get("error") or "Okta githubUsername empty; GitHub membership not scanned"
        return f"• `{app['app']}` — identity_unresolved — {detail}"
    line = f"• `{app['app']}` — {app.get('status')}"
    if app.get("error_class"):
        line += f" ({app.get('error_class')})"
    return line


def _ttl_epoch() -> int:
    return int((datetime.now(timezone.utc) + timedelta(days=DYNAMODB_TTL_DAYS)).timestamp())


def _get_existing(run_date: str, user_id: str) -> dict[str, Any] | None:
    resp = _table.get_item(
        Key={"run_date": run_date, "user_id": user_id},
        ConsistentRead=True,
    )
    return resp.get("Item")


def persist_findings(item: dict[str, Any]) -> None:
    # Sparse GSI: DynamoDB rejects empty-string index keys. Omit until JSM
    # returns a real issue key (persist-before-ticket used to write "").
    clean = dict(item)
    if not (clean.get("jira_issue_key") or "").strip():
        clean.pop("jira_issue_key", None)
    _table.put_item(Item=clean)


def _jql_guard(email: str, run_id: str) -> str:
    safe_email = email.replace('"', "")
    safe_run = run_id.replace('"', "")
    return (
        f'project = {JIRA_PROJECT_KEY} AND "Request Type" = "License Reclamation" '
        f'AND "Leaver email" ~ "{safe_email}" AND "Offboarding run ID" = "{safe_run}"'
    )


def _ticket_fields(payload: dict[str, str], findings: list[dict[str, Any]]) -> dict[str, Any]:
    actives = active_app_keys(findings)
    apps_field = ", ".join(actives) if actives else "none"
    notes = error_notes(findings)
    identity_only = bool(_identity_apps(findings)) and not _connector_error_apps(findings)
    if notes and identity_only:
        scan_line = f"Identity: {notes}"
    elif notes:
        scan_line = f"Scan errors: {notes}"
    else:
        scan_line = "No connector errors."
    description = (
        f"License scan for {payload['user_email']} (Okta {payload['okta_id']}). "
        f"Active seats: {apps_field}. "
        + scan_line
    )
    return {
        "project": {"key": JIRA_PROJECT_KEY},
        "issuetype": {"id": JIRA_ISSUE_TYPE_ID},
        "summary": f"License reclamation: {payload['user_email']}",
        "description": adf_doc(description),
        CF_REQUEST_TYPE: JIRA_REQUEST_TYPE_ID,
        CF_LEAVER_EMAIL: payload["user_email"],
        CF_OKTA_USER_ID: payload["okta_id"],
        CF_OFFBOARDING_RUN_ID: payload["run_id"],
        CF_APPS: apps_field,
        CF_NOTES: notes,
    }


def _reuse_or_create_ticket(
    payload: dict[str, str],
    findings: list[dict[str, Any]],
    existing_key: str | None,
) -> tuple[str | None, bool]:
    """Return (issue_key, created). created=False means reused. Raises on create failure."""
    if existing_key:
        comment = (
            f"Re-scan {payload['run_date']}: active={active_app_keys(findings) or ['none']}. "
            f"{error_notes(findings) or 'No connector errors.'}"
        )
        add_comment(
            cloud_id=JIRA_CLOUD_ID,
            auth_email=JIRA_EMAIL,
            token=_JIRA_API_TOKEN,
            issue_key=existing_key,
            text=comment,
        )
        update_issue(
            cloud_id=JIRA_CLOUD_ID,
            auth_email=JIRA_EMAIL,
            token=_JIRA_API_TOKEN,
            issue_key=existing_key,
            fields={
                CF_APPS: ", ".join(active_app_keys(findings)) if active_app_keys(findings) else "none",
                CF_NOTES: error_notes(findings),
            },
        )
        return existing_key, False

    status, issues = search_issues(
        cloud_id=JIRA_CLOUD_ID,
        auth_email=JIRA_EMAIL,
        token=_JIRA_API_TOKEN,
        jql=_jql_guard(payload["user_email"], payload["run_id"]),
    )
    if status == 200 and issues:
        key = issues[0].get("key")
        if key:
            return _reuse_or_create_ticket(payload, findings, key)

    http_status, body = create_issue(
        cloud_id=JIRA_CLOUD_ID,
        auth_email=JIRA_EMAIL,
        token=_JIRA_API_TOKEN,
        fields=_ticket_fields(payload, findings),
    )
    if http_status in (200, 201) and body.get("key"):
        return body["key"], True

    _log({
        "event": "jira_create_failed",
        "okta_id": payload["okta_id"],
        "login": payload["user_email"],
        "run_id": payload["run_id"],
        "run_date": payload["run_date"],
        "error_class": "work_queue",
        "http_status": http_status,
        "retryable": http_status == 429 or (http_status or 0) >= 500,
        "error": str(body)[:500],
    })
    raise RuntimeError(f"JSM create failed HTTP {http_status}")


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


def _slack_summary(
    payload: dict[str, str],
    findings: list[dict[str, Any]],
    row_status: str,
    issue_key: str | None,
    extra_error: str | None = None,
) -> dict[str, Any]:
    enabled = _enabled(findings)
    actives = active_app_keys(findings)
    errors = _connector_error_apps(findings)
    identity = _identity_apps(findings)
    if row_status == NO_LICENSES_TO_RECLAIM and not errors and not identity:
        text = (
            f":white_check_mark: License scan — {payload['user_email']} "
            f"(no licenses to reclaim)"
        )
    else:
        text = (
            f":ticket: License scan {row_status} — {payload['user_email']}"
            + (f" [{issue_key}]" if issue_key else "")
        )
    lines = [_format_app_line(a) for a in enabled]
    if extra_error:
        lines.append(f"• work-queue: {extra_error}")
    summary = (
        f"*Leaver:* `{payload['user_email']}`\n"
        f"*Status:* `{row_status}`"
        + (f"  *Ticket:* `{issue_key}`" if issue_key else "")
        + (f"\n*Active:* {', '.join(actives) or 'none'}")
        + (f"\n*Errors:* {', '.join(errors) or 'none'}")
    )
    if identity:
        summary += f"\n*Identity:* {', '.join(identity)} (Okta githubUsername empty; GitHub membership not scanned)"
    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🪪 License scan — {payload['run_date']}"},
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": summary,
            },
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Apps:*\n" + "\n".join(lines)},
        },
        {
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": (
                    f"run_id: `{payload['run_id']}` • okta_id: `{payload['okta_id']}` "
                    f"• Posted by NovaTech IT Ops automation"
                ),
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


def _base_item(payload: dict[str, str], findings: list[dict[str, Any]]) -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "run_date": payload["run_date"],
        "user_id": payload["okta_id"],
        "login": payload["user_email"],
        "okta_id": payload["okta_id"],
        "first_name": payload.get("first_name") or "",
        "last_name": payload.get("last_name") or "",
        "apps": findings,
        "jira_issue_key": "",
        "status": "",
        "correlation_id": f"OFFBOARD-{payload['run_id']}",
        "error_class": None,
        "ttl_epoch": _ttl_epoch(),
        "timestamp_utc": now_utc,
        "run_id": payload["run_id"],
        "github_username": payload.get("github_username") or "",
    }


def lambda_handler(event, context):  # noqa: ARG001
    dry_run = False
    try:
        detail, dry_run = _unwrap_event(event)
        payload = _validate_payload(detail)
    except Exception as exc:
        _log({
            "event": "license_scan_failed",
            "error_class": "infra",
            "retryable": False,
            "error": str(exc)[:500],
        })
        raise

    apps_config = _load_apps_config()
    findings = scan_enabled_apps(payload, apps_config)
    row_status, row_error_class = compute_row_status(findings)
    existing = None if dry_run else _get_existing(payload["run_date"], payload["okta_id"])
    existing_key = (existing or {}).get("jira_issue_key") or None
    if existing_key == "":
        existing_key = None

    item = _base_item(payload, findings)
    item["status"] = row_status
    item["error_class"] = row_error_class
    ticket_wanted = needs_ticket(findings)
    issue_key = existing_key
    jsm_failed = False
    persist_failed = False
    extra_error = None

    plan = {
        "event": "license_scan_plan" if dry_run else "license_scan_complete",
        "dry_run": dry_run,
        "run_date": payload["run_date"],
        "run_id": payload["run_id"],
        "okta_id": payload["okta_id"],
        "login": payload["user_email"],
        "status": row_status,
        "error_class": row_error_class,
        "ticket_wanted": ticket_wanted,
        "apps": findings,
        "active_apps": active_app_keys(findings),
    }

    if dry_run:
        _log(plan)
        return plan

    try:
        persist_findings(item)
    except Exception as exc:
        persist_failed = True
        extra_error = f"dynamodb: {exc}"[:500]
        _log({
            "event": "license_scan_failed",
            "error_class": "infra",
            "run_date": payload["run_date"],
            "run_id": payload["run_id"],
            "okta_id": payload["okta_id"],
            "login": payload["user_email"],
            "correlation_id": item["correlation_id"],
            "retryable": True,
            "error": extra_error,
            "apps": findings,
        })

    if ticket_wanted and not persist_failed:
        try:
            issue_key, _created = _reuse_or_create_ticket(payload, findings, existing_key)
            item["jira_issue_key"] = issue_key or ""
            item["correlation_id"] = f"JIRA-{issue_key}" if issue_key else item["correlation_id"]
            if row_status == "error" and row_error_class == "all_connectors_failed":
                item["error_class"] = "all_connectors_failed"
            persist_findings(item)
        except Exception as exc:
            jsm_failed = True
            extra_error = str(exc)[:500]
            item["status"] = "error"
            item["error_class"] = "work_queue"
            row_status = "error"
            row_error_class = "work_queue"
            try:
                persist_findings(item)
            except Exception as persist_exc:
                persist_failed = True
                extra_error = f"{extra_error}; dynamodb: {persist_exc}"[:500]

    slack_result = _slack_summary(payload, findings, row_status, issue_key, extra_error)
    correlation_id = item.get("correlation_id") or f"OFFBOARD-{payload['run_id']}"
    result = {
        **plan,
        "event": "license_scan_complete",
        "status": row_status,
        "error_class": row_error_class,
        "jira_issue_key": issue_key,
        "correlation_id": correlation_id,
        "slack": slack_result,
        "apps": findings,
    }

    should_raise = persist_failed or jsm_failed or row_error_class == "all_connectors_failed"
    if should_raise:
        error_class = "infra" if persist_failed else (
            "work_queue" if jsm_failed else "all_connectors_failed"
        )
        result["event"] = "license_scan_failed"
        result["error_class"] = error_class
        _log(result)
        raise RuntimeError(f"license_scan_failed:{error_class}")

    _log(result)
    return result
