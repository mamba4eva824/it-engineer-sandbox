#!/usr/bin/env python3
"""Invoke the license reclaim orchestrator Lambda (Phase 5 agentic path).

The HITL skill remains the default. This CLI runs the same orchestrator
Lambda on demand so a single ticket can be planned without flipping the
EventBridge auto-run flag.

Usage:
  python scripts/licenses/orchestrate.py --issue SUP-10 --dry-run
  python scripts/licenses/orchestrate.py --issue SUP-10 --apply
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _invoke(issue_key: str, *, dry_run: bool) -> dict:
    import boto3

    payload = {
        "issue_key": issue_key,
        "dry_run": dry_run,
        "source": "cli",
    }
    client = boto3.client("lambda", region_name=os.environ.get("AWS_REGION", "us-west-1"))
    resp = client.invoke(
        FunctionName=os.environ.get(
            "LICENSE_ORCHESTRATOR_FUNCTION_NAME",
            "ohmgym-license-reclaim-orchestrator",
        ),
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    body = resp["Payload"].read().decode()
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = {"raw": body}
    usage = parsed.get("usage") if isinstance(parsed, dict) else None
    if usage:
        print(json.dumps({"usage": usage}, indent=2))
    return parsed


def main() -> int:
    parser = argparse.ArgumentParser(description="License reclaim orchestrator CLI")
    parser.add_argument("--issue", required=True, help="JSM issue key, e.g. SUP-10")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Plan + broker dry-run; no live revoke, no Done")
    mode.add_argument("--apply", action="store_true", help="Plan, live broker POST, comment, maybe Done")
    args = parser.parse_args()
    _load_dotenv()
    result = _invoke(args.issue, dry_run=bool(args.dry_run))
    print(json.dumps(result, indent=2, default=str))
    if isinstance(result, dict) and result.get("error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
