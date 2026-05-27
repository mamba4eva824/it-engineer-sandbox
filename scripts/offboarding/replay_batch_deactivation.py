#!/usr/bin/env python3
"""Replay the offboarding batch for a chosen date via event.override_date.

Part of scripts/offboarding/ — see README.md for operator remediation.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import boto3

LAMBDA_NAME = "ohmgym-offboarding-workflow"
DEFAULT_REGION = "us-west-1"


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay offboarding batch for a given date.")
    parser.add_argument("--date", default=_today_pt(), help="YYYY-MM-DD (default: today PT)")
    parser.add_argument("--region", default=DEFAULT_REGION)
    args = parser.parse_args()

    client = boto3.client("lambda", region_name=args.region)
    payload = {"override_date": args.date}
    print(f"Replaying {LAMBDA_NAME} for run_date={args.date}")
    resp = client.invoke(
        FunctionName=LAMBDA_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode(),
    )
    body = json.loads(resp["Payload"].read().decode())
    print(json.dumps(body, indent=2))
    return 0 if not resp.get("FunctionError") else 1


if __name__ == "__main__":
    raise SystemExit(main())
