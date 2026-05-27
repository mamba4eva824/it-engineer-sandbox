#!/usr/bin/env python3
"""Invoke the ohmgym-offboarding-workflow Lambda from your laptop.

Part of scripts/offboarding/ — see README.md for phased demo steps.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone

import boto3

LAMBDA_NAME = "ohmgym-offboarding-workflow"
LOG_GROUP = "/aws/lambda/ohmgym-offboarding-workflow"
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
        parsed = body
    return {
        "status_code": resp["StatusCode"],
        "function_error": resp.get("FunctionError"),
        "response": parsed,
    }


def _tail_logs(client, seconds: int = 60) -> None:
    end = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    start = datetime.now(timezone.utc) - timedelta(minutes=5)
    print(f"--- Tailing {LOG_GROUP} for {seconds}s ---")
    seen: set[str] = set()
    while datetime.now(timezone.utc) < end:
        resp = client.filter_log_events(
            logGroupName=LOG_GROUP,
            startTime=int(start.timestamp() * 1000),
            limit=50,
        )
        for ev in resp.get("events", []):
            msg = ev.get("message", "").strip()
            if msg and msg not in seen:
                seen.add(msg)
                print(msg)
        time.sleep(2)


def main() -> int:
    parser = argparse.ArgumentParser(description="Invoke the offboarding workflow Lambda.")
    parser.add_argument("--date", help="override_date YYYY-MM-DD for replay")
    parser.add_argument("--region", default=DEFAULT_REGION)
    parser.add_argument("--tail-logs", action="store_true")
    args = parser.parse_args()

    payload: dict = {}
    if args.date:
        payload["override_date"] = args.date

    client = boto3.client("lambda", region_name=args.region)
    print(f"Invoking {LAMBDA_NAME} in {args.region} with payload: {json.dumps(payload)}")
    result = _invoke(client, payload)
    print(json.dumps(result, indent=2))

    if args.tail_logs:
        logs = boto3.client("logs", region_name=args.region)
        _tail_logs(logs)

    if result.get("function_error"):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
