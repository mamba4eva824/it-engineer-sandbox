#!/usr/bin/env python3
"""Local license-scan CLI (dry-run connectors or invoke the Lambda).

Usage:
  python scripts/licenses/scan_cli.py --email chris@ohmgym.com --okta-id 00u... \\
      --run-id local --run-date 2026-08-14 --github-username mamba4eva824 --dry-run

  python scripts/licenses/scan_cli.py --email ... --okta-id ... --run-id ... \\
      --run-date ... --invoke
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

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


def _local_scan(args: argparse.Namespace) -> dict:
    sys.path.insert(0, str(LICENSES_DIR))
    from github_client import scan_github
    from jira_client import scan_jira
    from linear_client import DEFAULT_ORG_UUID, scan_linear

    findings = [
        scan_github(
            org=os.environ.get("GITHUB_ORG", "ohmgym-sandbox"),
            token=os.environ.get("GITHUB_READ_TOKEN", ""),
            login=args.github_username,
        ),
        scan_linear(
            api_key=os.environ.get("LINEAR_API_KEY", ""),
            email=args.email,
            expected_org_uuid=os.environ.get("LINEAR_ORG_UUID", DEFAULT_ORG_UUID),
        ),
        scan_jira(
            email=args.email,
            token=os.environ.get("JIRA_API_TOKEN", ""),
            auth_email=os.environ.get("JIRA_EMAIL", ""),
            cloud_id=os.environ.get("JIRA_CLOUD_ID", ""),
        ),
    ]
    return {
        "event": "license_scan_plan",
        "dry_run": True,
        "user_email": args.email,
        "okta_id": args.okta_id,
        "run_id": args.run_id,
        "run_date": args.run_date,
        "github_username": args.github_username,
        "apps": findings,
    }


def _invoke_lambda(args: argparse.Namespace) -> dict:
    import boto3

    payload = {
        "user_email": args.email,
        "okta_id": args.okta_id,
        "run_id": args.run_id,
        "run_date": args.run_date,
        "github_username": args.github_username,
        "dry_run": args.dry_run,
    }
    client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    resp = client.invoke(
        FunctionName=os.environ.get("LICENSE_SCANNER_FUNCTION_NAME", "ohmgym-license-scanner"),
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    body = resp["Payload"].read().decode()
    try:
        return json.loads(body)
    except ValueError:
        return {"raw": body}


def main() -> int:
    parser = argparse.ArgumentParser(description="License scanner CLI")
    parser.add_argument("--email", required=True)
    parser.add_argument("--okta-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-date", required=True)
    parser.add_argument("--github-username", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--invoke", action="store_true", help="Invoke the deployed Lambda")
    args = parser.parse_args()
    _load_dotenv()
    if args.invoke:
        result = _invoke_lambda(args)
    else:
        result = _local_scan(args)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
