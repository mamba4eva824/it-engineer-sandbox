#!/usr/bin/env python3
"""
Update Auth0 NovaTech user emails from @novatech.io to @your-domain.com.

Aligns Auth0 user emails with the Google Cloud Identity domain (your-domain.com)
so SAML NameID matches across both platforms.

Also updates manager_email references in user_metadata.

Prerequisites:
  1. pip install auth0-python python-dotenv
  2. .env file with AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET
  3. Users already provisioned in Auth0

Usage:
  python update_user_emails.py --dry-run    # Preview changes
  python update_user_emails.py              # Execute migration
"""

import argparse
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

try:
    from auth0.management import Auth0
    from auth0.authentication import GetToken
except ImportError:
    print("ERROR: auth0-python not installed. Run: pip install auth0-python")
    sys.exit(1)

OLD_DOMAIN = "novatech.io"
NEW_DOMAIN = "your-domain.com"


def get_management_client():
    """Authenticate and return an Auth0 Management API client."""
    domain = os.getenv("AUTH0_DOMAIN")
    client_id = os.getenv("AUTH0_CLIENT_ID")
    client_secret = os.getenv("AUTH0_CLIENT_SECRET")

    if not all([domain, client_id, client_secret]):
        print("ERROR: Missing Auth0 credentials in .env file.")
        print("Required: AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET")
        sys.exit(1)

    get_token = GetToken(domain, client_id, client_secret=client_secret)
    token = get_token.client_credentials(f"https://{domain}/api/v2/")
    mgmt_api_token = token["access_token"]

    return Auth0(tenant_domain=domain, token=mgmt_api_token)


def get_all_users(auth0_client):
    """Fetch all users with @novatech.io emails."""
    users = []
    page = 0
    per_page = 100
    while True:
        pager = auth0_client.users.list(
            page=page,
            per_page=per_page,
            q=f'email.domain:"{OLD_DOMAIN}"',
            fields="user_id,email,user_metadata",
        )
        batch = pager.items if hasattr(pager, "items") else pager.get("users", [])
        if not batch:
            break
        users.extend(batch)
        if len(batch) < per_page:
            break
        page += 1
    return users


def transform_email(email):
    """Transform @novatech.io email to @your-domain.com."""
    if email and email.endswith(f"@{OLD_DOMAIN}"):
        local_part = email.split("@")[0]
        return f"{local_part}@{NEW_DOMAIN}"
    return email


def update_user(auth0_client, user, dry_run=False):
    """Update a single user's email and manager_email."""
    user_id = user.user_id if hasattr(user, "user_id") else user["user_id"]
    old_email = user.email if hasattr(user, "email") else user["email"]
    metadata = user.user_metadata if hasattr(user, "user_metadata") else user.get("user_metadata", {})

    new_email = transform_email(old_email)
    if new_email == old_email:
        return False  # No change needed

    # Build update payload
    update_body = {"email": new_email, "email_verified": True}

    # Also update manager_email in user_metadata if it has the old domain
    manager_email = metadata.get("manager_email", "") if metadata else ""
    if manager_email and manager_email.endswith(f"@{OLD_DOMAIN}"):
        new_manager = transform_email(manager_email)
        update_body["user_metadata"] = {"manager_email": new_manager}

    if dry_run:
        manager_info = ""
        if "user_metadata" in update_body:
            manager_info = f" (manager: {manager_email} → {update_body['user_metadata']['manager_email']})"
        print(f"  [DRY RUN] {old_email} → {new_email}{manager_info}")
        return True

    try:
        auth0_client.users.update(id=user_id, **update_body)
        print(f"  Updated: {old_email} → {new_email}")
        return True
    except Exception as e:
        print(f"  FAILED: {old_email} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description=f"Migrate Auth0 user emails from @{OLD_DOMAIN} to @{NEW_DOMAIN}"
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without updating")
    args = parser.parse_args()

    print(f"Email migration: @{OLD_DOMAIN} → @{NEW_DOMAIN}")

    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***\n")

    # Connect
    auth0_client = get_management_client()
    print("Connected to Auth0 Management API")

    # Fetch users
    print("Fetching users...")
    users = get_all_users(auth0_client)
    print(f"Found {len(users)} users with @{OLD_DOMAIN} emails\n")

    if not users:
        print("No users to update.")
        return

    # Update in batches
    batch_size = 10
    success = 0
    skipped = 0
    failed = 0

    for i in range(0, len(users), batch_size):
        batch = users[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(users) + batch_size - 1) // batch_size
        print(f"Batch {batch_num}/{total_batches}:")

        for user in batch:
            result = update_user(auth0_client, user, args.dry_run)
            if result:
                success += 1
            elif result is False:
                skipped += 1
            else:
                failed += 1

        # Rate limit
        if not args.dry_run and i + batch_size < len(users):
            print("  (pausing 1s for rate limits...)")
            time.sleep(1)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"EMAIL MIGRATION COMPLETE")
    print(f"  Updated:  {success}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")
    print(f"  Total:    {success + skipped + failed}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
