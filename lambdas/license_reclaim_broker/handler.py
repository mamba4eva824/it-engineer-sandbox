"""AWS Lambda handler for the ohmgym license reclaim broker (Phase 3).

Wired to a Lambda Function URL (HTTPS, authorization_type=NONE — the caller
authenticates with a shared secret in the Authorization header, same pattern
as lambdas/okta_activation_handler). This is the **only** thing in the
license-reclamation architecture allowed to hold SaaS write credentials
(ADR-005) — Cursor/Claude calls this endpoint, never GitHub/Linear/Jira
admin APIs directly.

POST body:
  {
    "issue_key": "SUP-2",
    "requested_by": "chris@ohmgym.com",
    "apps": ["github", "linear"],
    "dry_run": true
  }

Handler flow (mirrors the scanner's per-app continue-on-error style, ADR-010):
  1. Validate the shared secret.
  2. Parse + validate the body; reject unknown or disabled app keys up front
     with HTTP 400 — no SaaS/DynamoDB calls at all for the whole request.
  3. Query the DynamoDB GSI on jira_issue_key -> 404 if no finding row exists.
  4. Per requested app: must be status="active" in the row's *scan* findings
     (P3-R5 — never revoke an app whose scan status is "error" or
     "identity_unresolved"). Already-`reclaimed` apps are skipped
     idempotently.
  5. dry_run (the default) returns the plan only — no write-secret fetch, no
     SaaS call, no DynamoDB write.
  6. Live: call the per-app write function independently (one app's failure
     never blocks another); merge outcomes into the row's `reclaim` list and
     roll the row's overall `status` up to `reclaimed` (all active apps
     succeeded) or `partial`.
  7. Best-effort Jira comment summarizing outcomes — failure is logged, never
     raises (mirrors the scanner's Slack-is-best-effort contract).

Write secrets (github-write, linear-write, jira-write) are fetched lazily,
only inside a live (non-dry-run) reclaim, and only for the app being revoked
right then — never at cold start, and never for a dry-run request.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import boto3

_HERE = Path(__file__).resolve().parent
_SCRIPTS_LICENSES = _HERE.parent.parent / "scripts" / "licenses"
if _SCRIPTS_LICENSES.is_dir():
    sys.path.insert(0, str(_SCRIPTS_LICENSES))

from github_client import remove_org_member  # noqa: E402
from jira_client import add_comment, deactivate_user, remove_product_access  # noqa: E402
from linear_client import DEFAULT_ORG_UUID, suspend_user  # noqa: E402

SECRETS_REGION = os.environ.get("SECRETS_REGION", "us-west-1")
WEBHOOK_SECRET_NAME = os.environ["WEBHOOK_SECRET_NAME"]
GITHUB_WRITE_SECRET_NAME = os.environ["GITHUB_WRITE_SECRET_NAME"]
LINEAR_WRITE_SECRET_NAME = os.environ["LINEAR_WRITE_SECRET_NAME"]
JIRA_WRITE_SECRET_NAME = os.environ["JIRA_WRITE_SECRET_NAME"]
JIRA_READ_SECRET_NAME = os.environ["JIRA_READ_SECRET_NAME"]
GITHUB_ORG = os.environ.get("GITHUB_ORG", "ohmgym-sandbox")
JIRA_CLOUD_ID = os.environ.get("JIRA_CLOUD_ID", "")
JIRA_EMAIL = os.environ.get("JIRA_EMAIL", "")
LINEAR_ORG_UUID = os.environ.get("LINEAR_ORG_UUID", DEFAULT_ORG_UUID)
DYNAMODB_TABLE_NAME = os.environ["DYNAMODB_TABLE_NAME"]
DYNAMODB_ISSUE_KEY_INDEX = os.environ.get("DYNAMODB_ISSUE_KEY_INDEX", "jira_issue_key-index")

_secrets_client = boto3.client("secretsmanager", region_name=SECRETS_REGION)
_dynamodb = boto3.resource("dynamodb", region_name=SECRETS_REGION)
_table = _dynamodb.Table(DYNAMODB_TABLE_NAME)

_secret_cache: dict[str, str] = {}


def _fetch_secret(name: str) -> str:
    if name not in _secret_cache:
        _secret_cache[name] = _secrets_client.get_secret_value(SecretId=name)["SecretString"]
    return _secret_cache[name]


# Only the inbound webhook secret is fetched at cold start. Write secrets stay
# lazy so a dry-run request never touches Secrets Manager for revoke tokens.
_WEBHOOK_SECRET = _fetch_secret(WEBHOOK_SECRET_NAME)


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


def _http_response(status: int, body: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def query_by_issue_key(issue_key: str) -> dict[str, Any] | None:
    resp = _table.query(
        IndexName=DYNAMODB_ISSUE_KEY_INDEX,
        KeyConditionExpression="jira_issue_key = :k",
        ExpressionAttributeValues={":k": issue_key},
        Limit=1,
    )
    items = resp.get("Items") or []
    return items[0] if items else None


def _finding_for_app(row: dict[str, Any], app_key: str) -> dict[str, Any] | None:
    for f in row.get("apps") or []:
        if f.get("app") == app_key:
            return f
    return None


def _existing_reclaim(row: dict[str, Any], app_key: str) -> dict[str, Any] | None:
    for r in row.get("reclaim") or []:
        if r.get("app") == app_key:
            return r
    return None


def plan_for_app(app_key: str, row: dict[str, Any]) -> dict[str, Any]:
    """Idempotent + P3-R5 eligibility check. Never returns "eligible" for a
    scan status of "error" or "identity_unresolved" — only "active" apps
    (the scan-result vocabulary) are ever revocable.
    """
    existing = _existing_reclaim(row, app_key)
    if existing and existing.get("status") == "reclaimed":
        return {"app": app_key, "outcome": "already_reclaimed"}
    finding = _finding_for_app(row, app_key)
    if not finding or finding.get("status") != "active":
        return {"app": app_key, "outcome": "not_active_in_findings"}
    return {"app": app_key, "outcome": "eligible"}


def validate_request(
    body: dict[str, Any], apps_config: dict[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, list[str] | None]:
    """Returns (error_response, request, requested_apps). Exactly one of
    error_response or (request, requested_apps) is non-None.
    """
    issue_key = str(body.get("issue_key") or "").strip()
    if not issue_key:
        return _http_response(400, {"error": "issue_key is required"}), None, None
    apps = body.get("apps")
    if not isinstance(apps, list) or not apps:
        return _http_response(400, {"error": "apps must be a non-empty list"}), None, None
    unknown = [a for a in apps if a not in apps_config]
    if unknown:
        return _http_response(400, {"error": f"unknown app(s): {unknown}"}), None, None
    disabled = [a for a in apps if not apps_config[a].get("enabled")]
    if disabled:
        return _http_response(400, {"error": f"disabled app(s): {disabled}"}), None, None
    return None, {
        "issue_key": issue_key,
        "requested_by": str(body.get("requested_by") or "").strip() or "unknown",
        "dry_run": bool(body.get("dry_run", True)),
    }, apps


def _write_secret_name_for(app_key: str) -> str:
    return {
        "github": GITHUB_WRITE_SECRET_NAME,
        "linear": LINEAR_WRITE_SECRET_NAME,
        "jira": JIRA_WRITE_SECRET_NAME,
    }[app_key]


def _revoke_github(row: dict[str, Any], write_token: str) -> dict[str, Any]:
    return remove_org_member(
        org=GITHUB_ORG,
        token=write_token,
        login=row.get("github_username") or None,
    )


def _revoke_linear(row: dict[str, Any], write_token: str) -> dict[str, Any]:
    return suspend_user(
        api_key=write_token,
        email=row["login"],
        expected_org_uuid=LINEAR_ORG_UUID,
    )


def _revoke_jira(row: dict[str, Any], write_token: str, apps_config: dict[str, Any]) -> dict[str, Any]:
    """Try each configured Jira action in order; stop at the first "reclaimed".

    apps.json lists ["remove_product_access", "deactivate_user"] — the
    group-removal fallback is tried first since it works with a standard
    scoped API token, while deactivate_user needs org-admin API access that
    personal/non-domain-claimed Atlassian sites likely do not have. If every
    action errors, the last action's error is returned.
    """
    read_token = _fetch_secret(JIRA_READ_SECRET_NAME)
    spec = apps_config.get("jira") or {}
    group_name = spec.get("product_group") or "jira-servicemanagement-users-buffett-dev"
    last: dict[str, Any] | None = None
    for action in spec.get("actions") or ["remove_product_access"]:
        if action == "remove_product_access":
            result = remove_product_access(
                email=row["login"],
                write_token=write_token,
                read_token=read_token,
                auth_email=JIRA_EMAIL,
                cloud_id=JIRA_CLOUD_ID,
                group_name=group_name,
            )
        elif action == "deactivate_user":
            result = deactivate_user(
                email=row["login"],
                write_token=write_token,
                read_token=read_token,
                auth_email=JIRA_EMAIL,
                cloud_id=JIRA_CLOUD_ID,
            )
        else:
            continue
        if result.get("status") == "reclaimed":
            return result
        last = result
    return last or {
        "app": "jira",
        "status": "error",
        "error_class": "misconfig",
        "retryable": False,
        "error": "no jira write action configured",
    }


def revoke_one(app_key: str, row: dict[str, Any], apps_config: dict[str, Any]) -> dict[str, Any]:
    write_token = _fetch_secret(_write_secret_name_for(app_key))
    if app_key == "jira":
        return _revoke_jira(row, write_token, apps_config)
    if app_key == "linear":
        return _revoke_linear(row, write_token)
    if app_key == "github":
        return _revoke_github(row, write_token)
    return {
        "app": app_key,
        "status": "error",
        "error_class": "misconfig",
        "retryable": False,
        "error": f"no revoke action wired for {app_key}",
    }


def update_reclaim(row: dict[str, Any], results: list[dict[str, Any]], requested_by: str) -> str:
    """Merge new per-app outcomes onto the row's `reclaim` list; return the
    row's new overall status (`reclaimed` if every active app has succeeded,
    else `partial`).
    """
    merged_by_app = {r["app"]: r for r in (row.get("reclaim") or [])}
    for res in results:
        merged_by_app[res["app"]] = res
    merged = list(merged_by_app.values())

    active_apps = [a["app"] for a in row.get("apps") or [] if a.get("status") == "active"]
    all_reclaimed = bool(active_apps) and all(
        (merged_by_app.get(a) or {}).get("status") == "reclaimed" for a in active_apps
    )
    new_status = "reclaimed" if all_reclaimed else "partial"

    _table.update_item(
        Key={"run_date": row["run_date"], "user_id": row["user_id"]},
        UpdateExpression="SET reclaim = :r, #s = :s, reclaimed_by = :rb, reclaimed_at = :ra",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={
            ":r": merged,
            ":s": new_status,
            ":rb": requested_by,
            ":ra": _now_iso(),
        },
    )
    return new_status


def post_jira_comment(issue_key: str, results: list[dict[str, Any]]) -> None:
    try:
        read_token = _fetch_secret(JIRA_READ_SECRET_NAME)
        lines = [f"{r['app']}: {r.get('status', r.get('outcome'))}" for r in results]
        add_comment(
            cloud_id=JIRA_CLOUD_ID,
            auth_email=JIRA_EMAIL,
            token=read_token,
            issue_key=issue_key,
            text="License reclaim broker results:\n" + "\n".join(lines),
        )
    except Exception as exc:  # best-effort; never raises (mirrors scanner Slack contract)
        _log({"event": "broker_comment_failed", "issue_key": issue_key, "error": str(exc)[:500]})


def lambda_handler(event, context):  # noqa: ARG001
    """Lambda Function URL entry point. `event` is the Lambda URL event format."""
    method = event.get("requestContext", {}).get("http", {}).get("method", "POST").upper()
    if method != "POST":
        return _http_response(405, {"error": f"method {method} not allowed"})

    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    if headers.get("authorization", "") != _WEBHOOK_SECRET:
        return _http_response(401, {"error": "unauthorized"})

    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError as exc:
        return _http_response(400, {"error": f"invalid json: {exc}"})

    apps_config = _load_apps_config()
    error_response, req, requested_apps = validate_request(body, apps_config)
    if error_response:
        return error_response

    row = query_by_issue_key(req["issue_key"])
    if not row:
        return _http_response(404, {"error": f"no findings for issue_key {req['issue_key']}"})

    plan = [plan_for_app(app_key, row) for app_key in requested_apps]

    if req["dry_run"]:
        result = {
            "event": "license_reclaim_plan",
            "dry_run": True,
            "issue_key": req["issue_key"],
            "plan": plan,
        }
        _log(result)
        return _http_response(200, result)

    eligible = {p["app"] for p in plan if p["outcome"] == "eligible"}
    results: list[dict[str, Any]] = []
    for p in plan:
        if p["app"] not in eligible:
            results.append({"app": p["app"], "outcome": p["outcome"]})
            continue
        try:
            outcome = revoke_one(p["app"], row, apps_config)
        except Exception as exc:
            outcome = {
                "status": "error",
                "error_class": "retryable",
                "retryable": True,
                "error": str(exc)[:500],
            }
            _log({
                "event": "broker_connector_error",
                "app": p["app"],
                "issue_key": req["issue_key"],
                "error": str(exc)[:500],
            })
        results.append({**outcome, "app": p["app"], "requested_by": req["requested_by"], "at": _now_iso()})

    new_status = None
    if eligible:
        new_status = update_reclaim(row, [r for r in results if r["app"] in eligible], req["requested_by"])
        post_jira_comment(req["issue_key"], results)

    response = {
        "event": "license_reclaim_complete",
        "dry_run": False,
        "issue_key": req["issue_key"],
        "requested_by": req["requested_by"],
        "row_status": new_status,
        "results": results,
    }
    _log(response)
    return _http_response(200, response)
