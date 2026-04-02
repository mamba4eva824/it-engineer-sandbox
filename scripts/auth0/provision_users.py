#!/usr/bin/env python3
"""
Provision NovaTech users into Auth0 using the Management API (v5 SDK).

Prerequisites:
  1. pip install auth0-python python-dotenv
  2. Create a .env file with:
     AUTH0_DOMAIN=dev-xxxxx.us.auth0.com
     AUTH0_CLIENT_ID=your_m2m_client_id
     AUTH0_CLIENT_SECRET=your_m2m_client_secret
  3. Run generate_users.py first to create novatech_users.json

Usage:
  python provision_users.py                  # Provision all users
  python provision_users.py --count 10       # Provision first 10 users
  python provision_users.py --department Engineering  # Provision only Engineering
  python provision_users.py --dry-run        # Preview without creating
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Auth0 SDK imports
try:
    from auth0.management import Auth0
    from auth0.authentication import GetToken
except ImportError:
    print("ERROR: auth0-python not installed. Run: pip install auth0-python")
    sys.exit(1)


def get_management_client():
    """Authenticate and return an Auth0 Management API client."""
    domain = os.getenv("AUTH0_DOMAIN")
    client_id = os.getenv("AUTH0_CLIENT_ID")
    client_secret = os.getenv("AUTH0_CLIENT_SECRET")

    if not all([domain, client_id, client_secret]):
        print("ERROR: Missing Auth0 credentials in .env file.")
        print("Required: AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET")
        sys.exit(1)

    # Get M2M access token
    get_token = GetToken(domain, client_id, client_secret=client_secret)
    token = get_token.client_credentials(f"https://{domain}/api/v2/")
    mgmt_api_token = token["access_token"]

    return Auth0(tenant_domain=domain, token=mgmt_api_token)


def get_existing_emails(auth0_client):
    """Fetch all existing user emails to avoid duplicates."""
    existing = set()
    page = 0
    per_page = 100
    while True:
        pager = auth0_client.users.list(
            page=page, per_page=per_page, fields=["email"]
        )
        if not pager.items:
            break
        for u in pager.items:
            email = u.email if hasattr(u, "email") else u.get("email", "")
            existing.add(email.lower())
        if len(pager.items) < per_page:
            break
        page += 1
    return existing


def get_or_create_roles(auth0_client, required_roles):
    """Ensure all required Auth0 roles exist and return a name->id map."""
    existing_roles = auth0_client.roles.list()
    role_map = {}
    for r in existing_roles.items:
        name = r.name if hasattr(r, "name") else r["name"]
        rid = r.id if hasattr(r, "id") else r["id"]
        role_map[name] = rid

    for role_name in required_roles:
        if role_name not in role_map:
            print(f"  Creating role: {role_name}")
            new_role = auth0_client.roles.create(
                name=role_name, description=f"NovaTech {role_name} role"
            )
            role_map[role_name] = new_role.id

    return role_map


def provision_user(auth0_client, user_data, role_map, dry_run=False):
    """Create a single user and assign their role."""
    email = user_data["email"]
    role_name = user_data["auth0_role"]

    if dry_run:
        print(f"  [DRY RUN] Would create: {email} ({role_name})")
        return True

    try:
        # Create the user via v5 keyword args
        created = auth0_client.users.create(
            email=user_data["email"],
            name=user_data["name"],
            given_name=user_data["given_name"],
            family_name=user_data["family_name"],
            password=user_data["password"],
            connection=user_data["connection"],
            email_verified=user_data["email_verified"],
            user_metadata=user_data["user_metadata"],
            app_metadata=user_data["app_metadata"],
        )
        user_id = created.user_id if hasattr(created, "user_id") else created["user_id"]

        # Assign role
        if role_name in role_map:
            auth0_client.roles.users.assign(
                id=role_map[role_name], users=[user_id]
            )

        print(f"  Created: {email} -> {role_name}")
        return True

    except Exception as e:
        print(f"  FAILED: {email} -- {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Provision NovaTech users into Auth0")
    parser.add_argument("--count", type=int, help="Number of users to provision")
    parser.add_argument("--department", help="Only provision users in this department")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    args = parser.parse_args()

    # Load user data
    data_path = Path(__file__).parent / "novatech_users.json"
    if not data_path.exists():
        print("ERROR: novatech_users.json not found. Run generate_users.py first.")
        sys.exit(1)

    with open(data_path) as f:
        all_users = json.load(f)

    # Filter by department if specified
    if args.department:
        all_users = [
            u for u in all_users
            if u["user_metadata"]["department"].lower() == args.department.lower()
        ]
        print(f"Filtered to {len(all_users)} users in {args.department}")

    # Limit count if specified
    if args.count:
        all_users = all_users[: args.count]

    print(f"\nProvisioning {len(all_users)} users into Auth0")
    if args.dry_run:
        print("*** DRY RUN MODE -- no changes will be made ***\n")

    # Connect to Auth0
    if not args.dry_run:
        auth0_client = get_management_client()
        print("Connected to Auth0 Management API")

        # Check for existing users
        print("Checking for existing users...")
        existing_emails = get_existing_emails(auth0_client)
        new_users = [u for u in all_users if u["email"].lower() not in existing_emails]
        skipped = len(all_users) - len(new_users)
        if skipped > 0:
            print(f"Skipping {skipped} users that already exist")
        all_users = new_users

        # Ensure roles exist
        required_roles = list({u["auth0_role"] for u in all_users})
        print(f"Ensuring {len(required_roles)} roles exist...")
        role_map = get_or_create_roles(auth0_client, required_roles)
    else:
        auth0_client = None
        role_map = {}

    # Provision in batches of 10
    batch_size = 10
    success = 0
    failed = 0

    for i in range(0, len(all_users), batch_size):
        batch = all_users[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(all_users) + batch_size - 1) // batch_size
        print(f"\nBatch {batch_num}/{total_batches}:")

        for user in batch:
            if provision_user(auth0_client, user, role_map, args.dry_run):
                success += 1
            else:
                failed += 1

        # Rate limit: pause between batches
        if not args.dry_run and i + batch_size < len(all_users):
            print("  (pausing 1s for rate limits...)")
            time.sleep(1)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"PROVISIONING COMPLETE")
    print(f"  Successful: {success}")
    print(f"  Failed:     {failed}")
    print(f"  Total:      {success + failed}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
