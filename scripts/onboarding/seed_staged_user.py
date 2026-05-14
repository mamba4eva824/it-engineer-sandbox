#!/usr/bin/env python3
"""Provision a STAGED Okta test user with a chosen startDate.

Use this to set up the end-to-end smoke test for the onboarding_workflow
Lambda — create a STAGED user whose profile.startDate matches today (or any
chosen date), then invoke the Lambda with `invoke_onboarding_workflow.py`
and confirm the user transitions STAGED → PROVISIONED and an activation
email lands in the chosen inbox.

Reuses the existing Okta API plumbing from scripts/okta/_client.py for the
session + auth dance — same .env, same Private Key JWT.

Usage:
  python scripts/onboarding/seed_staged_user.py \\
    --first-name Priya --last-name Patel \\
    --email chris+priya@ohmgym.com \\
    --department Data --role-title "Data Engineer" \\
    --start-date 2026-05-14

Defaults --start-date to today (America/Los_Angeles).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# Reuse the existing Okta client (Private Key JWT + session).
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "okta"))
from _client import api_url, get_session  # noqa: E402


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Provision a STAGED Okta user for the onboarding-workflow smoke test.")
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--email", required=True, help="Will also be used as profile.login.")
    parser.add_argument("--department", default="Data")
    parser.add_argument("--role-title", default="Data Engineer")
    parser.add_argument("--cost-center", default="DAT-100")
    parser.add_argument("--manager-email", default="heather.gutierrez@ohmgym.com")
    parser.add_argument("--start-date", default=_today_pt(), help="ISO date YYYY-MM-DD; defaults to today PT.")
    parser.add_argument("--dry-run", action="store_true", help="Print the would-be payload, don't POST.")
    args = parser.parse_args()

    profile = {
        "firstName": args.first_name,
        "lastName": args.last_name,
        "email": args.email,
        "login": args.email,
        "department": args.department,
        "costCenter": args.cost_center,
        "role_title": args.role_title,
        "managerEmail": args.manager_email,
        "startDate": args.start_date,
    }
    body = {"profile": profile}

    if args.dry_run:
        print("DRY RUN — would POST to /api/v1/users?activate=false:")
        print(json.dumps(body, indent=2))
        return 0

    session, _scopes = get_session()

    # Dedup: skip if a user with this login already exists.
    dedup_resp = session.get(
        api_url("/api/v1/users"),
        params={"search": f'profile.login eq "{args.email}"', "limit": 10},
        timeout=15,
    )
    dedup_resp.raise_for_status()
    existing = dedup_resp.json()
    if existing:
        u = existing[0]
        print(f"Skipped: user already exists. id={u['id']} status={u.get('status')}")
        return 0

    # Create with activate=false → user lands in STAGED with no activation email yet.
    resp = session.post(
        api_url("/api/v1/users"),
        params={"activate": "false"},
        data=json.dumps(body),
        timeout=20,
    )
    if resp.status_code not in (200, 201):
        print(f"ERROR: create failed: HTTP {resp.status_code}")
        print(resp.text)
        return 1
    user = resp.json()
    print(json.dumps({
        "created": True,
        "id": user["id"],
        "status": user.get("status"),
        "login": user["profile"]["login"],
        "startDate": user["profile"]["startDate"],
        "note": "User is STAGED. Run invoke_onboarding_workflow.py to activate + email.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
