#!/usr/bin/env python3
"""License reclaim CLI (Phase 3) — dry-run by default, matching the repo's
`reconcile_config.py --audit/--apply` convention.

This is what a service-desk agent runs from Cursor/Claude via a
natural-language prompt (e.g. "reclaim GitHub and Linear for SUP-2, dry-run
first"). It never needs raw SaaS write tokens once `--invoke` is used —
only the deployed broker's Function URL + shared webhook secret leave the
agent's environment.

Three modes:

  Local dry-run (default): query DynamoDB directly (AWS creds required) for
  the finding row, print which requested apps are eligible/skipped. No
  writes anywhere.

      python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear

  Local apply: same local DynamoDB query, then call the connector write
  functions directly using *.env* write tokens (GITHUB_WRITE_TOKEN,
  LINEAR_WRITE_KEY, JIRA_WRITE_TOKEN) and update DynamoDB directly. Useful
  for testing connectors before the broker Lambda is deployed/applied.

      python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --apply

  Invoke the deployed broker (the real path for Phase 4 / service-desk
  agents): POST to the Function URL with the shared webhook secret. No AWS
  credentials or SaaS write tokens touch this process at all.

      python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --invoke
      python scripts/licenses/reclaim.py --issue SUP-2 --apps github,linear --invoke --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
LICENSES_DIR = Path(__file__).resolve().parent


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def _dynamodb_table():
    import boto3

    region = os.environ.get("AWS_REGION", "us-west-1")
    table_name = os.environ.get("DYNAMODB_TABLE_NAME", "ohmgym-license-reclaim-logs")
    return boto3.resource("dynamodb", region_name=region).Table(table_name)


def _query_by_issue_key(issue_key: str) -> dict[str, Any] | None:
    table = _dynamodb_table()
    index_name = os.environ.get("DYNAMODB_ISSUE_KEY_INDEX", "jira_issue_key-index")
    resp = table.query(
        IndexName=index_name,
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


def _plan_for_app(app_key: str, row: dict[str, Any], *, force: bool = False) -> dict[str, Any]:
    existing = _existing_reclaim(row, app_key)
    if existing and existing.get("status") == "reclaimed" and not force:
        return {"app": app_key, "outcome": "already_reclaimed"}
    finding = _finding_for_app(row, app_key)
    if not finding or finding.get("status") != "active":
        return {"app": app_key, "outcome": "not_active_in_findings"}
    return {"app": app_key, "outcome": "eligible"}


def _load_apps_config() -> dict[str, Any]:
    path = ROOT / "config" / "licenses" / "apps.json"
    return json.loads(path.read_text())


def _revoke_one_local(app_key: str, row: dict[str, Any], apps_config: dict[str, Any]) -> dict[str, Any]:
    sys.path.insert(0, str(LICENSES_DIR))
    from github_client import remove_org_member
    from jira_client import deactivate_user, product_access_groups, remove_product_access
    from linear_client import DEFAULT_ORG_UUID, suspend_user

    if app_key == "github":
        write_token = os.environ.get("GITHUB_WRITE_TOKEN") or os.environ.get("GITHUB_READ_TOKEN", "")
        return remove_org_member(
            org=os.environ.get("GITHUB_ORG", "ohmgym-sandbox"),
            token=write_token,
            login=row.get("github_username") or None,
        )
    if app_key == "linear":
        write_key = os.environ.get("LINEAR_WRITE_KEY") or os.environ.get("LINEAR_API_KEY", "")
        return suspend_user(
            api_key=write_key,
            email=row["login"],
            expected_org_uuid=os.environ.get("LINEAR_ORG_UUID", DEFAULT_ORG_UUID),
        )
    if app_key == "jira":
        write_token = os.environ.get("JIRA_WRITE_TOKEN") or os.environ.get("JIRA_API_TOKEN", "")
        read_token = os.environ.get("JIRA_API_TOKEN", "")
        spec = apps_config.get("jira") or {}
        groups = product_access_groups(spec)
        last: dict[str, Any] | None = None
        for action in spec.get("actions") or ["remove_product_access"]:
            if action == "remove_product_access":
                result = remove_product_access(
                    email=row["login"],
                    write_token=write_token,
                    read_token=read_token,
                    auth_email=os.environ.get("JIRA_EMAIL", ""),
                    cloud_id=os.environ.get("JIRA_CLOUD_ID", ""),
                    groups=groups,
                )
            elif action == "deactivate_user":
                result = deactivate_user(
                    email=row["login"],
                    write_token=write_token,
                    read_token=read_token,
                    auth_email=os.environ.get("JIRA_EMAIL", ""),
                    cloud_id=os.environ.get("JIRA_CLOUD_ID", ""),
                )
            else:
                continue
            if result.get("status") == "reclaimed":
                return result
            last = result
        return last or {"app": "jira", "status": "error", "error_class": "misconfig", "error": "no jira action configured"}
    return {"app": app_key, "status": "error", "error_class": "misconfig", "error": f"no revoke action for {app_key}"}


def _update_reclaim_local(row: dict[str, Any], results: list[dict[str, Any]], requested_by: str) -> str:
    from datetime import datetime, timezone

    from row_status import compute_reclaim_row_status

    table = _dynamodb_table()

    merged_by_app = {r["app"]: r for r in (row.get("reclaim") or [])}
    for res in results:
        merged_by_app[res["app"]] = res
    merged = list(merged_by_app.values())

    new_status = compute_reclaim_row_status(row.get("apps") or [], merged_by_app)
    now_iso = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    table.update_item(
        Key={"run_date": row["run_date"], "user_id": row["user_id"]},
        UpdateExpression="SET reclaim = :r, #s = :s, reclaimed_by = :rb, reclaimed_at = :ra",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":r": merged, ":s": new_status, ":rb": requested_by, ":ra": now_iso},
    )
    return new_status


def _run_local(args: argparse.Namespace) -> dict[str, Any]:
    apps_config = _load_apps_config()
    requested_apps = [a.strip() for a in args.apps.split(",") if a.strip()]
    unknown = [a for a in requested_apps if a not in apps_config]
    if unknown:
        return {"error": f"unknown app(s): {unknown}"}
    disabled = [a for a in requested_apps if not apps_config[a].get("enabled")]
    if disabled:
        return {"error": f"disabled app(s): {disabled}"}

    row = _query_by_issue_key(args.issue)
    if not row:
        return {"error": f"no findings for issue_key {args.issue}"}

    plan = [_plan_for_app(a, row, force=args.force) for a in requested_apps]

    if not args.apply:
        return {
            "event": "license_reclaim_plan",
            "dry_run": True,
            "issue_key": args.issue,
            "plan": plan,
        }

    eligible = {p["app"] for p in plan if p["outcome"] == "eligible"}
    results = []
    for p in plan:
        if p["app"] not in eligible:
            results.append({"app": p["app"], "outcome": p["outcome"]})
            continue
        outcome = _revoke_one_local(p["app"], row, apps_config)
        results.append({**outcome, "app": p["app"], "requested_by": args.requested_by})

    row_status = None
    if eligible:
        row_status = _update_reclaim_local(row, [r for r in results if r["app"] in eligible], args.requested_by)

    return {
        "event": "license_reclaim_complete",
        "dry_run": False,
        "issue_key": args.issue,
        "requested_by": args.requested_by,
        "row_status": row_status,
        "results": results,
    }


def _run_invoke(args: argparse.Namespace) -> dict[str, Any]:
    import requests

    url = os.environ.get("BROKER_FUNCTION_URL", "")
    secret = os.environ.get("BROKER_WEBHOOK_SECRET", "")
    if not url:
        return {"error": "BROKER_FUNCTION_URL is not set (see terraform output broker_function_url)"}
    if not secret:
        return {"error": "BROKER_WEBHOOK_SECRET is not set (see terraform output broker_webhook_secret_name)"}

    payload = {
        "issue_key": args.issue,
        "requested_by": args.requested_by,
        "apps": [a.strip() for a in args.apps.split(",") if a.strip()],
        "dry_run": not args.apply,
        "force": bool(args.force),
    }
    resp = requests.post(
        url,
        headers={"Authorization": secret, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    try:
        return resp.json()
    except ValueError:
        return {"http_status": resp.status_code, "raw": resp.text}


def main() -> int:
    _load_dotenv()
    parser = argparse.ArgumentParser(description="License reclaim broker CLI (Phase 3)")
    parser.add_argument("--issue", required=True, help="JSM issue key, e.g. SUP-2")
    parser.add_argument("--apps", required=True, help="Comma-separated app keys, e.g. github,linear")
    parser.add_argument(
        "--requested-by",
        default=os.environ.get("JIRA_EMAIL", "cli"),
        help="Recorded on the reclaim row / broker log as the human who requested this.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Perform the live revoke. Without this flag the command always dry-runs (repo convention).",
    )
    parser.add_argument(
        "--invoke",
        action="store_true",
        help="Call the deployed broker Function URL instead of running connectors locally.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-run apps already marked reclaimed (e.g. after product-access groups were added).",
    )
    args = parser.parse_args()

    result = _run_invoke(args) if args.invoke else _run_local(args)
    print(json.dumps(result, indent=2))
    return 0 if "error" not in result else 1


if __name__ == "__main__":
    raise SystemExit(main())
