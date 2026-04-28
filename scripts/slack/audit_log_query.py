#!/usr/bin/env python3
"""Query Slack's Enterprise Audit Logs API.

Primary use: diagnose the SAML 'sso_failed=1' error that is invisible in the
Slack admin UI. The audit log records the specific validation failure reason
(e.g. 'audience_mismatch', 'invalid_signature') that the UI hides behind its
generic error banner.

Usage:
  # Recent failed sign-ins (SAML debugging)
  python scripts/slack/audit_log_query.py --action user_login_failed --since 2h

  # SSO / SAML config activity
  python scripts/slack/audit_log_query.py --since 2h | grep -i sso

  # Filter to a specific actor
  python scripts/slack/audit_log_query.py --actor chris@ohmgym.com --since 24h

  # Dump raw JSON for a specific event action
  python scripts/slack/audit_log_query.py --action sso_settings_updated --raw --limit 5
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _client import SlackAPIError, get_session, paginate


def parse_since(s: str) -> int:
    """'2h' / '30m' / '24h' / '7d' -> Unix timestamp (seconds) N ago."""
    m = re.fullmatch(r"(\d+)([smhd])", s.strip())
    if not m:
        print(f"ERROR: --since must be like 30m, 2h, 24h, 7d (got {s!r})")
        sys.exit(1)
    n, unit = int(m.group(1)), m.group(2)
    mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return int(time.time()) - (n * mult)


def summarize(event: dict) -> str:
    """One-line summary of an audit event for console output."""
    ts = event.get("date_create", 0)
    iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)) if ts else "?"
    action = event.get("action", "?")
    actor = event.get("actor", {}).get("user", {})
    actor_label = actor.get("email") or actor.get("name") or event.get("actor", {}).get("type", "?")
    entity = event.get("entity", {})
    entity_type = entity.get("type", "")
    entity_label = ""
    if entity_type == "user":
        entity_label = entity.get("user", {}).get("email") or entity.get("user", {}).get("name", "")
    elif entity_type == "workspace":
        entity_label = entity.get("workspace", {}).get("name", "")
    elif entity_type == "enterprise":
        entity_label = entity.get("enterprise", {}).get("name", "")
    elif entity_type == "channel":
        entity_label = entity.get("channel", {}).get("name", "")
    details = event.get("details") or {}
    detail_bits = []
    for key in ("reason", "error", "type", "desktop_app_browser_quit", "sso_required"):
        if key in details:
            detail_bits.append(f"{key}={details[key]}")
    detail_str = (" | " + " ".join(detail_bits)) if detail_bits else ""
    return f"{iso}  {action:38s}  actor={actor_label:30s}  target={entity_type}:{entity_label}{detail_str}"


def main():
    parser = argparse.ArgumentParser(description="Query Slack Enterprise Audit Logs.")
    parser.add_argument("--action", help="Filter by action name (e.g. user_login_failed, sso_settings_updated).")
    parser.add_argument("--actor", help="Filter by actor email.")
    parser.add_argument("--entity", help="Filter by entity type: user, workspace, enterprise, channel, etc.")
    parser.add_argument("--since", default="2h", help="Time window (e.g. 30m, 2h, 24h, 7d). Default: 2h.")
    parser.add_argument("--limit", type=int, default=50, help="Max events to fetch (default 50).")
    parser.add_argument("--raw", action="store_true", help="Print full event JSON instead of summary lines.")
    args = parser.parse_args()

    params = {"limit": min(args.limit, 200), "oldest": parse_since(args.since)}
    if args.action:
        params["action"] = args.action
    if args.actor:
        # audit API filters by actor user id, not email — we post-filter below
        pass

    session = get_session()
    print(f"Querying Slack audit log: since={args.since} action={args.action or 'ANY'} actor={args.actor or 'ANY'} limit={args.limit}")
    print()

    count = 0
    try:
        for event in paginate(session, "logs", params=params, audit=True, items_key="entries"):
            if count >= args.limit:
                break
            if args.actor:
                actor_email = event.get("actor", {}).get("user", {}).get("email", "")
                if actor_email.lower() != args.actor.lower():
                    continue
            if args.entity:
                if event.get("entity", {}).get("type") != args.entity:
                    continue
            count += 1
            if args.raw:
                print(json.dumps(event, indent=2))
                print("---")
            else:
                print(summarize(event))
    except SlackAPIError as e:
        print(f"\nERROR: Slack API rejected the query: {e.error}")
        sys.exit(1)

    print()
    print(f"{count} event(s) matched.")


if __name__ == "__main__":
    main()
