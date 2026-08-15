#!/usr/bin/env python3
"""Query JML onboarding/offboarding/license-reclaim DynamoDB audit tables (read-only).

Uses the active AWS credential chain — configure a profile that assumes
ohmgym-grc-jml-audit-read (see terraform/aws-grc-audit outputs).

Usage:
  AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py --date 2026-06-10
  python scripts/grc/query_jml_audit.py --table offboarding --scan --max-items 5
  python scripts/grc/query_jml_audit.py --table reclaim --date 2026-08-15
  python scripts/grc/query_jml_audit.py --table all --scan --max-items 5
"""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal

import boto3

WEST = "us-west-1"
TABLES = {
    "onboarding": "ohmgym-onboarding-logs",
    "offboarding": "ohmgym-offboarding-logs",
    "reclaim": "ohmgym-license-reclaim-logs",
}
JML_KEYS = ("onboarding", "offboarding")


class DecimalEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Decimal):
            return int(o) if o % 1 == 0 else float(o)
        return super().default(o)


def query_by_date(table, run_date: str) -> list[dict]:
    resp = table.query(
        KeyConditionExpression="run_date = :d",
        ExpressionAttributeValues={":d": run_date},
    )
    return resp.get("Items", [])


def scan_table(table, max_items: int) -> list[dict]:
    resp = table.scan(Limit=max_items)
    return resp.get("Items", [])


def _targets(table_arg: str) -> list[str]:
    if table_arg == "all":
        return list(TABLES.keys())
    if table_arg == "both":
        return list(JML_KEYS)
    return [table_arg]


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only JML / license-reclaim audit table queries.")
    parser.add_argument(
        "--table",
        choices=("onboarding", "offboarding", "reclaim", "both", "all"),
        default="both",
        help="both = onboarding+offboarding; all = those plus reclaim.",
    )
    parser.add_argument("--date", help="run_date partition key (YYYY-MM-DD) for Query.")
    parser.add_argument("--scan", action="store_true", help="Scan instead of query (requires no --date).")
    parser.add_argument("--max-items", type=int, default=25)
    args = parser.parse_args()

    if args.scan and args.date:
        print("ERROR: use --date for Query or --scan, not both.")
        sys.exit(1)
    if not args.scan and not args.date:
        print("ERROR: provide --date for Query or --scan for a sample scan.")
        sys.exit(1)

    resource = boto3.resource("dynamodb", region_name=WEST)
    targets = _targets(args.table)

    for key in targets:
        name = TABLES[key]
        table = resource.Table(name)
        print(f"\n=== {name} ===")
        if args.scan:
            items = scan_table(table, args.max_items)
        else:
            items = query_by_date(table, args.date)
        print(json.dumps(items, indent=2, cls=DecimalEncoder))
        print(f"({len(items)} items)")


if __name__ == "__main__":
    main()
