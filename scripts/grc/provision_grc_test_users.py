#!/usr/bin/env python3
"""Provision GRC users from config/okta/grc_test_users.json.

Bryan Wong persona uses weinreichchris@gmail.com as login/email (Claude Desktop
Google OAuth) with firstName/lastName set independently. managerEmail is omitted
to avoid the @ohmgym.com pattern constraint on external emails.

Usage:
  python scripts/grc/provision_grc_test_users.py --dry-run
  python scripts/grc/provision_grc_test_users.py
"""

from __future__ import annotations

import argparse
import json
import secrets
import string
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "okta"))

from _client import api_url, get_session  # noqa: E402
from provision_users import create_user, generate_password, user_exists  # noqa: E402

GRC_TEST_USERS_JSON = REPO_ROOT / "config" / "okta" / "grc_test_users.json"


def build_grc_profile(user: dict) -> dict:
    m = user["user_metadata"]
    profile = {
        "firstName": user["given_name"],
        "lastName": user["family_name"],
        "email": user["email"],
        "login": user["email"],
        "department": m["department"],
        "costCenter": m["cost_center"],
        "role_title": m["role_title"],
        "startDate": m["start_date"],
    }
    if manager := m.get("manager_email"):
        profile["managerEmail"] = manager
    return profile


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision GRC test users into Okta.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not GRC_TEST_USERS_JSON.exists():
        print(f"ERROR: {GRC_TEST_USERS_JSON} not found.")
        sys.exit(1)

    users = json.loads(GRC_TEST_USERS_JSON.read_text())

    if args.dry_run:
        for u in users:
            print(f"Would create: {u['email']}")
        return

    session, _ = get_session()
    for i, u in enumerate(users):
        email = u["email"]
        profile = build_grc_profile(u)
        existing_id = user_exists(session, email)
        if existing_id:
            resp = session.post(
                api_url(f"/api/v1/users/{existing_id}"),
                json={"profile": profile},
                timeout=30,
            )
            if resp.status_code == 200:
                print(f"  Updated: {email}  ({profile['firstName']} {profile['lastName']})  id={existing_id}")
            else:
                print(f"  FAILED update: {email}  HTTP {resp.status_code}: {resp.text[:200]}")
                sys.exit(1)
            continue
        password = generate_password()
        status, detail = create_user(session, profile, password)
        if status == "created":
            print(f"  Created: {email}  id={detail}")
        else:
            print(f"  FAILED: {email}  {detail}")
            sys.exit(1)
        if i < len(users) - 1:
            time.sleep(1)


if __name__ == "__main__":
    main()
