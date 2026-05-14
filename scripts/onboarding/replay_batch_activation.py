#!/usr/bin/env python3
"""Replay the onboarding batch for a chosen date.

The 9:00 AM PT scheduled run filters Okta with a STRICT same-day match on
profile.startDate. If a run is missed (Lambda failed, AWS outage, account
suspended, etc.), the next day's run will NOT pick up yesterday's hires.
This CLI is the documented remediation path: pass --date YYYY-MM-DD to
re-trigger the activation for any past date.

The DynamoDB idempotency guard on (run_date, user_id) means re-running for
the same date is safe — already-activated users are skipped, and the audit
table records the additional run attempt.

Usage:
  # Replay yesterday's batch:
  python scripts/onboarding/replay_batch_activation.py --date 2026-05-13

  # Replay today (equivalent to a manual invoke):
  python scripts/onboarding/replay_batch_activation.py
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3

LAMBDA_NAME = "ohmgym-onboarding-workflow"
DEFAULT_REGION = "us-west-1"


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay the onboarding batch for a given date.")
    parser.add_argument("--date", default=_today_pt(), help="Run date (YYYY-MM-DD). Defaults to today PT.")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--dry-run", action="store_true", help="Print the payload that would be sent; don't invoke.")
    args = parser.parse_args()

    # Validate ISO date.
    try:
        datetime.fromisoformat(args.date)
    except ValueError:
        print(f"ERROR: --date must be ISO YYYY-MM-DD, got {args.date!r}")
        return 2

    payload = {"override_date": args.date}

    if args.dry_run:
        print(f"DRY RUN — would invoke {LAMBDA_NAME} in {args.region} with:")
        print(json.dumps(payload, indent=2))
        return 0

    print(f"Replaying {LAMBDA_NAME} for run_date={args.date}")
    client = boto3.client("lambda", region_name=args.region)
    resp = client.invoke(
        FunctionName=LAMBDA_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    body = resp["Payload"].read().decode()
    try:
        result = json.loads(body)
    except json.JSONDecodeError:
        result = {"raw": body}
    print(json.dumps({
        "status_code": resp.get("StatusCode"),
        "function_error": resp.get("FunctionError"),
        "response": result,
    }, indent=2))
    return 1 if resp.get("FunctionError") else 0


if __name__ == "__main__":
    sys.exit(main())
