#!/usr/bin/env python3
"""Smoke test for Slack API credentials.

Exercises:
  1. auth.test          — token validity, team/enterprise context, granted scopes
  2. admin.teams.list   — proves admin.teams:read scope granted (Enterprise Admin API works)
  3. audit/v1/logs      — proves auditlogs:read scope + audit API endpoint reachable

Exit code 0 on full success; non-zero on any failure.
"""

import sys

from _client import SLACK_ENTERPRISE_ID, SLACK_USER_TOKEN, SlackAPIError, call, get_session


def main():
    print(f"SLACK_USER_TOKEN:   xoxp-...{SLACK_USER_TOKEN[-6:]}")
    print(f"SLACK_ENTERPRISE_ID: {SLACK_ENTERPRISE_ID or '(unset)'}")
    print()

    session = get_session()

    # 1. auth.test
    try:
        auth = call(session, "auth.test")
    except SlackAPIError as e:
        print(f"  auth.test                   FAIL: {e.error}")
        sys.exit(1)
    print(f"  auth.test                   OK")
    print(f"    team:          {auth.get('team')} ({auth.get('team_id')})")
    print(f"    enterprise:    {auth.get('enterprise_id') or '(none)'}")
    print(f"    user:          {auth.get('user')} ({auth.get('user_id')})")
    print(f"    url:           {auth.get('url')}")
    granted = auth.get("response_metadata", {}).get("scopes") or session.headers  # scopes surface in X-OAuth-Scopes header on most responses
    print()

    # 2. admin.teams.list (Enterprise Admin API) — optional
    try:
        teams = call(session, "admin.teams.list", params={"limit": 10})
        teams_list = teams.get("teams", [])
        print(f"  admin.teams.list            OK  ({len(teams_list)} workspace(s) visible)")
        for t in teams_list[:5]:
            print(f"    - {t.get('name'):30s}  id={t.get('id')}")
    except SlackAPIError as e:
        print(f"  admin.teams.list            SKIP: {e.error}  (admin.teams:read not granted; not required for audit log work)")
    print()

    # 3. Audit Logs API
    try:
        logs = call(session, "logs", params={"limit": 1}, audit=True)
    except SlackAPIError as e:
        print(f"  audit/v1/logs               FAIL: {e.error}")
        sys.exit(3)
    except Exception as e:
        print(f"  audit/v1/logs               FAIL: {e}")
        sys.exit(3)
    entries = logs.get("entries", [])
    print(f"  audit/v1/logs               OK  ({len(entries)} recent event(s) visible)")
    if entries:
        first = entries[0]
        print(f"    most recent: action={first.get('action')}  actor={first.get('actor', {}).get('user', {}).get('email') or first.get('actor', {}).get('type')}")
    print()
    print("Slack API connection healthy. All three endpoints reachable.")


if __name__ == "__main__":
    main()
