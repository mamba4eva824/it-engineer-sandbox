#!/usr/bin/env python3
"""Invoke the ohmgym-onboarding-workflow Lambda from your laptop.

Use this for ad-hoc demos / smoke tests / development. It's a thin wrapper
around `boto3 lambda.invoke` that pretty-prints the response payload and
optionally tails CloudWatch Logs for the next ~60 seconds.

Usage:
  python scripts/onboarding/invoke_onboarding_workflow.py
  python scripts/onboarding/invoke_onboarding_workflow.py --date 2026-05-14
  python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs

For production scheduled runs, EventBridge Scheduler fires the Lambda
automatically — this script is just for development.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3

LAMBDA_NAME = "ohmgym-onboarding-workflow"
LOG_GROUP = "/aws/lambda/ohmgym-onboarding-workflow"
DEFAULT_REGION = "us-west-1"


def _invoke(client, payload: dict) -> dict:
    resp = client.invoke(
        FunctionName=LAMBDA_NAME,
        InvocationType="RequestResponse",
        LogType="Tail",
        Payload=json.dumps(payload).encode(),
    )
    body = resp["Payload"].read().decode()
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {"raw": body}
    return {
        "status_code": resp.get("StatusCode"),
        "function_error": resp.get("FunctionError"),
        "response": parsed,
    }


def _tail_logs(region: str, seconds: int = 60) -> None:
    logs = boto3.client("logs", region_name=region)
    start_ms = int((datetime.now(timezone.utc) - timedelta(seconds=10)).timestamp() * 1000)
    end_at = time.time() + seconds
    seen: set[str] = set()
    print(f"--- Tailing {LOG_GROUP} for {seconds}s ---")
    while time.time() < end_at:
        try:
            resp = logs.filter_log_events(
                logGroupName=LOG_GROUP,
                startTime=start_ms,
                limit=200,
            )
        except logs.exceptions.ResourceNotFoundException:
            print("(log group not yet created — wait for first invocation)")
            time.sleep(5)
            continue
        for ev in resp.get("events", []):
            eid = ev["eventId"]
            if eid in seen:
                continue
            seen.add(eid)
            ts = datetime.fromtimestamp(ev["timestamp"] / 1000, tz=timezone.utc).strftime("%H:%M:%S")
            print(f"[{ts}] {ev['message'].rstrip()}")
        time.sleep(3)


def main() -> int:
    parser = argparse.ArgumentParser(description="Invoke ohmgym-onboarding-workflow Lambda.")
    parser.add_argument("--date", help="Override the run_date (YYYY-MM-DD). Defaults to today PT inside the Lambda.")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--tail-logs", action="store_true", help="After invoke, tail CloudWatch Logs for 60s.")
    args = parser.parse_args()

    payload: dict = {}
    if args.date:
        payload["override_date"] = args.date

    print(f"Invoking {LAMBDA_NAME} in {args.region} with payload: {payload}")
    client = boto3.client("lambda", region_name=args.region)
    result = _invoke(client, payload)
    print(json.dumps(result, indent=2))

    if result.get("function_error"):
        print(f"\nFUNCTION ERROR: {result['function_error']}")
        if args.tail_logs:
            _tail_logs(args.region, seconds=30)
        return 1

    if args.tail_logs:
        _tail_logs(args.region, seconds=60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
