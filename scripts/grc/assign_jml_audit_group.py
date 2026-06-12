#!/usr/bin/env python3
"""Assign users to the access-jml-audit Okta group.

Group membership is manual today (reconcile_config.py does not manage user→group).
Use after provisioning Bryan Wong and the GRC test user.

Usage:
  python scripts/grc/assign_jml_audit_group.py --dry-run
  python scripts/grc/assign_jml_audit_group.py
  python scripts/grc/assign_jml_audit_group.py --email bryan.wong@ohmgym.com
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "okta"))

from _client import api_url, get_session, paginate  # noqa: E402

GROUP_NAME = "access-jml-audit"
DEFAULT_EMAILS = ("weinreichchris@gmail.com",)


def find_group_id(session, name: str) -> str:
    for group in paginate(session, api_url("/api/v1/groups"), params={"limit": 200}):
        if group.get("profile", {}).get("name") == name:
            return group["id"]
    raise SystemExit(f"ERROR: group '{name}' not found in Okta tenant")


def find_user_id(session, login: str) -> str | None:
    resp = session.get(
        api_url("/api/v1/users"),
        params={"search": f'profile.login eq "{login}"', "limit": 1},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    return results[0]["id"] if results else None


def is_member(session, group_id: str, user_id: str) -> bool:
    resp = session.get(
        api_url(f"/api/v1/groups/{group_id}/users/{user_id}"),
        timeout=15,
    )
    return resp.status_code == 200


def assign_member(session, group_id: str, user_id: str) -> None:
    resp = session.put(
        api_url(f"/api/v1/groups/{group_id}/users/{user_id}"),
        timeout=15,
    )
    resp.raise_for_status()


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign users to access-jml-audit.")
    parser.add_argument("--email", action="append", dest="emails", help="User login email (repeatable).")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    emails = args.emails or list(DEFAULT_EMAILS)

    if args.dry_run:
        print(f"Would assign to '{GROUP_NAME}': {', '.join(emails)}")
        return

    session, _ = get_session()
    group_id = find_group_id(session, GROUP_NAME)
    print(f"Group '{GROUP_NAME}' id={group_id}\n")

    for email in emails:
        user_id = find_user_id(session, email)
        if not user_id:
            print(f"  SKIP (user not found): {email}")
            continue
        if is_member(session, group_id, user_id):
            print(f"  Already member: {email}")
            continue
        assign_member(session, group_id, user_id)
        print(f"  Assigned: {email}")


if __name__ == "__main__":
    main()
