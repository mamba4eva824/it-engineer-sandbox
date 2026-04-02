#!/usr/bin/env python3
"""
Provision NovaTech users into Google Cloud Identity via the Directory API.

Creates users in the correct department OUs with @your-domain.com emails,
using the Auth0 novatech_users.json dataset as the source of truth.

Prerequisites:
  1. pip install google-auth google-api-python-client
  2. Service account with domain-wide delegation configured
  3. OAuth scopes granted: admin.directory.user
  4. OUs must exist (run create_ous.py first)

Usage:
  python provision_users.py --admin-email chris@your-domain.com               # Create all users
  python provision_users.py --admin-email chris@your-domain.com --dry-run     # Preview
  python provision_users.py --admin-email chris@your-domain.com --department Engineering
  python provision_users.py --admin-email chris@your-domain.com --count 10
"""

import argparse
import json
import sys
import time
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configuration ---

SERVICE_ACCOUNT_KEY = Path(__file__).parent.parent.parent / "credentials" / "service-account-key.json"
SCOPES = ["https://www.googleapis.com/auth/admin.directory.user"]
CUSTOMER_ID = "my_customer"
NOVATECH_USERS_JSON = Path(__file__).parent.parent / "auth0" / "novatech_users.json"
DEFAULT_PASSWORD = os.environ["GWS_DEFAULT_PASSWORD"]  # Set in .env


def get_directory_service(admin_email: str):
    """Authenticate via service account with domain-wide delegation."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def get_existing_emails(service):
    """Fetch all existing user emails to avoid duplicates."""
    existing = set()
    page_token = None
    while True:
        result = service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields="users(primaryEmail),nextPageToken",
        ).execute()
        for u in result.get("users", []):
            existing.add(u["primaryEmail"].lower())
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return existing


def provision_user(service, user_data, dry_run=False):
    """Create a single user in Google Cloud Identity."""
    email = user_data["email"]
    department = user_data["user_metadata"]["department"]
    role_title = user_data["user_metadata"]["role_title"]
    manager_email = user_data["user_metadata"].get("manager_email", "")
    cost_center = user_data["user_metadata"].get("cost_center", "")

    if dry_run:
        print(f"  [DRY RUN] Would create: {email} in /{department}")
        return True

    try:
        user_body = {
            "primaryEmail": email,
            "name": {
                "givenName": user_data["given_name"],
                "familyName": user_data["family_name"],
            },
            "password": DEFAULT_PASSWORD,
            "orgUnitPath": f"/{department}",
            "changePasswordAtNextLogin": False,
            "organizations": [
                {
                    "department": department,
                    "title": role_title,
                    "costCenter": cost_center,
                    "primary": True,
                }
            ],
            "relations": (
                [{"value": manager_email, "type": "manager"}]
                if manager_email
                else []
            ),
        }
        result = service.users().insert(body=user_body).execute()
        print(f"  Created: {email} in /{department}")
        return True
    except HttpError as e:
        if e.resp.status == 409:
            print(f"  Already exists: {email}")
            return True
        print(f"  FAILED: {email} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Provision NovaTech users into Google Cloud Identity"
    )
    parser.add_argument("--admin-email", required=True, help="Admin email to impersonate")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    parser.add_argument("--department", help="Only provision users in this department")
    parser.add_argument("--count", type=int, help="Number of users to provision")
    args = parser.parse_args()

    # Load user data
    if not NOVATECH_USERS_JSON.exists():
        print(f"ERROR: {NOVATECH_USERS_JSON} not found.")
        sys.exit(1)

    with open(NOVATECH_USERS_JSON) as f:
        all_users = json.load(f)

    # Filter by department
    if args.department:
        all_users = [
            u for u in all_users
            if u["user_metadata"]["department"].lower() == args.department.lower()
        ]
        print(f"Filtered to {len(all_users)} users in {args.department}")

    # Limit count
    if args.count:
        all_users = all_users[: args.count]

    print(f"\nProvisioning {len(all_users)} users into Google Cloud Identity")
    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***\n")

    # Connect
    if not args.dry_run:
        service = get_directory_service(args.admin_email)
        print("Connected to Google Directory API")

        # Check existing users
        print("Checking for existing users...")
        existing_emails = get_existing_emails(service)
        new_users = [u for u in all_users if u["email"].lower() not in existing_emails]
        skipped = len(all_users) - len(new_users)
        if skipped > 0:
            print(f"Skipping {skipped} users that already exist")
        all_users = new_users
    else:
        service = None

    # Provision in batches
    batch_size = 10
    success = 0
    failed = 0

    for i in range(0, len(all_users), batch_size):
        batch = all_users[i : i + batch_size]
        batch_num = (i // batch_size) + 1
        total_batches = (len(all_users) + batch_size - 1) // batch_size
        print(f"\nBatch {batch_num}/{total_batches}:")

        for user in batch:
            if provision_user(service, user, args.dry_run):
                success += 1
            else:
                failed += 1

        # Rate limit: Directory API allows ~1500 req/100s
        if not args.dry_run and i + batch_size < len(all_users):
            print("  (pausing 1s for rate limits...)")
            time.sleep(1)

    # Summary
    print(f"\n{'=' * 50}")
    print(f"GWS PROVISIONING COMPLETE")
    print(f"  Created:  {success}")
    print(f"  Failed:   {failed}")
    print(f"  Total:    {success + failed}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
