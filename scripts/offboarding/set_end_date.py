#!/usr/bin/env python3
"""Set profile.endDate on one or more Okta users by login, user id, or name.

Part of scripts/offboarding/ — see README.md for the full smoke-test loop.

Usage:
  python scripts/offboarding/set_end_date.py --login chris+alex@ohmgym.com --end-date 2026-05-27
  python scripts/offboarding/set_end_date.py --name "Alex Novak" --end-date 2026-05-27
  python scripts/offboarding/set_end_date.py --user-id 00uXXX --end-date 2026-05-27
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "okta"))
from _client import api_url, get_session  # noqa: E402


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _find_by_name(session, name: str) -> list[dict]:
    parts = name.strip().split(None, 1)
    if len(parts) == 2:
        first, last = parts
        search = f'profile.firstName eq "{first}" and profile.lastName eq "{last}"'
    else:
        search = f'profile.lastName eq "{parts[0]}" or profile.firstName eq "{parts[0]}"'
    resp = session.get(
        api_url("/api/v1/users"),
        params={"search": search, "limit": 20},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json() or []


def _find_by_login(session, login: str) -> dict | None:
    resp = session.get(
        api_url("/api/v1/users"),
        params={"search": f'profile.login eq "{login}"', "limit": 1},
        timeout=15,
    )
    resp.raise_for_status()
    users = resp.json() or []
    return users[0] if users else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Set Okta profile.endDate on user(s).")
    parser.add_argument("--end-date", default=_today_pt(), help="YYYY-MM-DD (default: today PT)")
    parser.add_argument("--login", action="append", default=[], help="profile.login (repeatable)")
    parser.add_argument("--user-id", action="append", default=[], help="Okta user id (repeatable)")
    parser.add_argument("--name", action="append", default=[], help='Full name e.g. "Alex Novak" (repeatable)')
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    datetime.fromisoformat(args.end_date)

    if not args.login and not args.user_id and not args.name:
        print("ERROR: provide at least one of --login, --user-id, or --name")
        return 1

    session, _scopes = get_session()
    targets: list[dict] = []

    for uid in args.user_id:
        resp = session.get(api_url(f"/api/v1/users/{uid}"), timeout=15)
        if resp.status_code == 404:
            print(f"WARN: user id not found: {uid}")
            continue
        resp.raise_for_status()
        targets.append(resp.json())

    for login in args.login:
        u = _find_by_login(session, login)
        if not u:
            print(f"WARN: login not found: {login}")
            continue
        targets.append(u)

    for name in args.name:
        found = _find_by_name(session, name)
        if not found:
            print(f"WARN: no users matched name: {name}")
            continue
        targets.extend(found)

    seen: set[str] = set()
    unique: list[dict] = []
    for u in targets:
        if u["id"] not in seen:
            seen.add(u["id"])
            unique.append(u)

    if not unique:
        print("ERROR: no users resolved")
        return 1

    for user in unique:
        profile = user.get("profile") or {}
        login = profile.get("login", user["id"])
        label = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or login
        if args.dry_run:
            print(f"  [DRY RUN] Would set endDate={args.end_date} on {label} ({login}) id={user['id']}")
            continue
        body = {"profile": {**profile, "endDate": args.end_date}}
        resp = session.put(api_url(f"/api/v1/users/{user['id']}"), json=body, timeout=15)
        if resp.status_code >= 300:
            print(f"  FAILED {label}: HTTP {resp.status_code} {resp.text[:300]}")
            continue
        print(f"  Set endDate={args.end_date} on {label} ({login}) status={user.get('status')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
