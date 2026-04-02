#!/usr/bin/env python3
"""
Create NovaTech department OUs in Google Cloud Identity via the Directory API.

Prerequisites:
  1. pip install google-auth google-api-python-client
  2. Service account with domain-wide delegation configured
  3. OAuth scopes granted: admin.directory.orgunit

Usage:
  python create_ous.py                  # Create all missing OUs
  python create_ous.py --dry-run        # Preview without creating
"""

import argparse
import json
import sys
from pathlib import Path

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# --- Configuration ---

SERVICE_ACCOUNT_KEY = Path(__file__).parent.parent.parent / "credentials" / "service-account-key.json"
ADMIN_EMAIL = None  # Set below after loading config
CUSTOMER_ID = "my_customer"  # "my_customer" refers to the account the admin belongs to

SCOPES = ["https://www.googleapis.com/auth/admin.directory.orgunit"]

# NovaTech department OUs to create under the root org
NOVATECH_OUS = [
    {"name": "Engineering", "description": "NovaTech Engineering department — Software Engineers, SREs, QA"},
    {"name": "IT-Ops", "description": "NovaTech IT Operations — Systems Engineers, Help Desk, IT Admins"},
    {"name": "Finance", "description": "NovaTech Finance department — Accounting, FP&A, Procurement"},
    {"name": "Executive", "description": "NovaTech Executive team — C-suite, VPs"},
    {"name": "Data", "description": "NovaTech Data department — Data Engineers, ML Engineers, Analysts"},
    {"name": "Product", "description": "NovaTech Product department — Product Managers, TPMs"},
    {"name": "Design", "description": "NovaTech Design department — UX/UI Designers, Researchers"},
    {"name": "HR", "description": "NovaTech Human Resources — People Ops, Recruiting, L&D"},
    {"name": "Sales", "description": "NovaTech Sales department — AEs, SDRs, Sales Ops"},
    {"name": "Marketing", "description": "NovaTech Marketing department — Growth, Content, Brand"},
]


def get_directory_service(admin_email: str):
    """Authenticate via service account with domain-wide delegation."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def get_existing_ous(service):
    """Fetch all existing OUs and return a set of names."""
    try:
        result = service.orgunits().list(customerId=CUSTOMER_ID).execute()
        ous = result.get("organizationUnits", [])
        return {ou["name"] for ou in ous}
    except HttpError as e:
        if e.resp.status == 404:
            return set()
        raise


def create_ou(service, name: str, description: str, dry_run: bool = False):
    """Create a single OU under the root org."""
    if dry_run:
        print(f"  [DRY RUN] Would create: /{name}")
        return True

    try:
        body = {
            "name": name,
            "description": description,
            "parentOrgUnitPath": "/",
        }
        service.orgunits().insert(customerId=CUSTOMER_ID, body=body).execute()
        print(f"  Created: /{name}")
        return True
    except HttpError as e:
        if e.resp.status == 409:
            print(f"  Already exists: /{name}")
            return True
        print(f"  FAILED: /{name} — {e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="Create NovaTech OUs in Google Cloud Identity")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    parser.add_argument("--admin-email", required=True, help="Admin email to impersonate (e.g., admin@your-domain.com)")
    args = parser.parse_args()

    print(f"Service account key: {SERVICE_ACCOUNT_KEY}")
    print(f"Admin email: {args.admin_email}")
    print(f"OUs to create: {len(NOVATECH_OUS)}")

    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***\n")

    # Authenticate
    if not args.dry_run:
        service = get_directory_service(args.admin_email)
        print("Connected to Google Directory API\n")

        # Check existing OUs
        existing = get_existing_ous(service)
        if existing:
            print(f"Existing OUs: {', '.join(sorted(existing))}")
    else:
        service = None
        existing = set()

    # Create missing OUs
    success = 0
    skipped = 0
    failed = 0

    for ou in NOVATECH_OUS:
        if ou["name"] in existing:
            print(f"  Skipping (exists): /{ou['name']}")
            skipped += 1
            continue

        if create_ou(service, ou["name"], ou["description"], args.dry_run):
            success += 1
        else:
            failed += 1

    # Summary
    print(f"\n{'=' * 50}")
    print(f"OU CREATION COMPLETE")
    print(f"  Created:  {success}")
    print(f"  Skipped:  {skipped}")
    print(f"  Failed:   {failed}")
    print(f"  Total:    {success + skipped + failed}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
