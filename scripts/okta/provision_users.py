#!/usr/bin/env python3
"""
Provision the curated NovaTech seed users into Okta via the Management API.

Reads config/okta/okta_seed_users.json (hand-maintained, Auth0-style user_metadata
shape) and POSTs each user to /api/v1/users?activate=true with a freshly-generated
password. Custom profile attributes (role_title, managerEmail, startDate) and base
profile dependencies (department, costCenter) are set at creation time so the
10 department group rules auto-assign membership within ~30 seconds.

Idempotent: pre-flight dedup via profile.login search; also tolerates E0000001
("already exists") as a skip if the dedup race loses.

Usage:
  python scripts/okta/provision_users.py --dry-run
  python scripts/okta/provision_users.py --department Engineering
  python scripts/okta/provision_users.py
"""

import argparse
import json
import secrets
import string
import sys
import time
from datetime import datetime
from pathlib import Path

from _client import api_url, get_session


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SEED_USERS_JSON = REPO_ROOT / "config" / "okta" / "okta_seed_users.json"
LOGS_DIR = REPO_ROOT / "logs"


def generate_password() -> str:
    """Strong random password satisfying Okta's default policy (upper, lower, digit, symbol, >=8)."""
    alphabet = string.ascii_letters + string.digits
    core = "".join(secrets.choice(alphabet) for _ in range(20))
    return f"A1a!{core}"


def build_profile(user: dict) -> dict:
    """Map Auth0-style user_metadata into Okta profile shape.

    - department and costCenter are base-profile dependencies (see
      baseProfileDependencies in config/okta/desired-state.json) — top-level keys.
    - role_title, managerEmail, startDate are custom attributes added by Phase 1.2 —
      also top-level keys in the flat Okta profile object.
    """
    m = user["user_metadata"]
    return {
        "firstName": user["given_name"],
        "lastName": user["family_name"],
        "email": user["email"],
        "login": user["email"],
        "department": m["department"],
        "costCenter": m["cost_center"],
        "role_title": m["role_title"],
        "managerEmail": m["manager_email"],
        "startDate": m["start_date"],
    }


def user_exists(session, login: str) -> str | None:
    """Return existing user's id if login is already present, else None."""
    resp = session.get(
        api_url("/api/v1/users"),
        params={"search": f'profile.login eq "{login}"', "limit": 10},
        timeout=15,
    )
    resp.raise_for_status()
    results = resp.json()
    return results[0]["id"] if results else None


def create_user(session, profile: dict, password: str) -> tuple[str, str]:
    """POST a user with activate=true. Returns (status, user_id_or_error)."""
    body = {"profile": profile, "credentials": {"password": {"value": password}}}
    resp = session.post(
        api_url("/api/v1/users"),
        params={"activate": "true"},
        json=body,
        timeout=30,
    )
    if resp.status_code == 200:
        return "created", resp.json()["id"]
    if resp.status_code == 400:
        body = resp.json()
        if body.get("errorCode") == "E0000001" and "already exists" in resp.text.lower():
            return "exists", ""
    return "failed", f"HTTP {resp.status_code}: {resp.text[:200]}"


def create_user_staged(session, profile: dict) -> tuple[str, str]:
    """POST a user with activate=false and no credentials. Returns (status, user_id_or_error).

    User lands in STAGED status. Caller must follow up with
    activate_user_with_email() to send the activation email and move them
    to PROVISIONED (or skip the email for a different activation path).
    """
    body = {"profile": profile}
    resp = session.post(
        api_url("/api/v1/users"),
        params={"activate": "false"},
        json=body,
        timeout=30,
    )
    if resp.status_code == 200:
        return "created", resp.json()["id"]
    if resp.status_code == 400:
        body = resp.json()
        if body.get("errorCode") == "E0000001" and "already exists" in resp.text.lower():
            return "exists", ""
    return "failed", f"HTTP {resp.status_code}: {resp.text[:200]}"


def activate_user_with_email(session, user_id: str) -> tuple[str, str]:
    """POST /users/{id}/lifecycle/activate?sendEmail=true. Returns (status, detail).

    Triggers Okta to send the activation email to the user's email address.
    On success the user moves from STAGED to PROVISIONED; the response body
    contains an activationUrl that's also embedded in the email.
    """
    resp = session.post(
        api_url(f"/api/v1/users/{user_id}/lifecycle/activate"),
        params={"sendEmail": "true"},
        timeout=15,
    )
    if resp.status_code == 200:
        return "activated", resp.json().get("activationUrl", "")
    return "failed", f"HTTP {resp.status_code}: {resp.text[:200]}"


def main():
    parser = argparse.ArgumentParser(description="Provision NovaTech seed users into Okta.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned payloads, make no API calls.")
    parser.add_argument("--department", help="Only provision users in this department (case-insensitive).")
    args = parser.parse_args()

    if not SEED_USERS_JSON.exists():
        print(f"ERROR: {SEED_USERS_JSON} not found.")
        sys.exit(1)

    with open(SEED_USERS_JSON) as f:
        users = json.load(f)

    if args.department:
        wanted = args.department.lower()
        users = [u for u in users if u["user_metadata"]["department"].lower() == wanted]
        print(f"Filtered to {len(users)} users in department '{args.department}'")

    print(f"\nProvisioning {len(users)} seed users into Okta")
    if args.dry_run:
        print("*** DRY RUN — no API calls will be made ***\n")
        for u in users:
            profile = build_profile(u)
            print(f"  Would create: {profile['login']} ({profile['department']})")
            payload = {"profile": profile, "credentials": {"password": {"value": "<redacted>"}}}
            print(f"    payload: {json.dumps(payload, indent=6)[:1000]}")
        return

    session, granted = get_session()
    print(f"Authenticated (granted scopes: {granted})\n")

    created, skipped, failed = [], [], []

    for i, u in enumerate(users):
        email = u["email"]
        existing_id = user_exists(session, email)
        if existing_id:
            print(f"  Skipped (exists): {email}  id={existing_id}")
            skipped.append({"email": email, "okta_user_id": existing_id})
            continue

        profile = build_profile(u)
        password = generate_password()
        status, detail = create_user(session, profile, password)

        if status == "created":
            print(f"  Created: {email}  id={detail}")
            created.append({"email": email, "okta_user_id": detail, "password": password})
        elif status == "exists":
            print(f"  Skipped (race): {email}")
            skipped.append({"email": email, "okta_user_id": ""})
        else:
            print(f"  FAILED: {email}  {detail}")
            failed.append({"email": email, "error": detail})

        if i < len(users) - 1:
            time.sleep(1)

    if created:
        LOGS_DIR.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        creds_path = LOGS_DIR / f"okta-seed-credentials-{timestamp}.json"
        with open(creds_path, "w") as f:
            json.dump(created, f, indent=2)
        creds_path.chmod(0o600)
        print(f"\nCredentials written to {creds_path.relative_to(REPO_ROOT)}")

    print(f"\n{'=' * 50}")
    print("OKTA SEED PROVISIONING COMPLETE")
    print(f"  Created: {len(created)}")
    print(f"  Skipped: {len(skipped)}")
    print(f"  Failed:  {len(failed)}")
    print(f"  Total:   {len(users)}")
    print(f"{'=' * 50}")

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
