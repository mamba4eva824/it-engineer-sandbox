#!/usr/bin/env python3
"""
Configure per-OU 2-Step Verification policies in Google Cloud Identity.

Uses the Cloud Identity Policy API (v1beta1) to set 2-Step Verification
enforcement and enrollment policies per organizational unit.

Policy design:
  - IT-Ops, Executive:  Enforce 2SV (already done for IT-Ops via console)
  - Finance, HR:        Enforce 2SV (sensitive data OUs)
  - All others:         Allow 2SV enrollment (optional)

Prerequisites:
  1. pip install google-auth google-api-python-client requests
  2. Cloud Identity API enabled in GCP project
  3. Service account with domain-wide delegation
  4. Scope: https://www.googleapis.com/auth/cloud-identity

Usage:
  python configure_2sv.py --dry-run    # Uses GWS_ADMIN_EMAIL from .env
  python configure_2sv.py              # Execute (requires Cloud Identity Premium for writes)
"""

import argparse
import json
import os
import sys
from pathlib import Path

import google.auth.transport.requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

# --- Configuration ---

SERVICE_ACCOUNT_KEY = Path(__file__).parent.parent.parent / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
ADMIN_SDK_SCOPES = ["https://www.googleapis.com/auth/admin.directory.orgunit"]
CLOUD_IDENTITY_SCOPES = ["https://www.googleapis.com/auth/cloud-identity.policies"]
CUSTOMER_ID = "my_customer"

# Per-OU 2-Step Verification policies
# "enforce" = all users must enroll in 2SV
# "allow" = users can opt in voluntarily
TWO_SV_POLICIES = {
    "IT-Ops": "enforce",       # Already done via console — script will skip if exists
    "Executive": "enforce",     # High-value targets, C-suite
    "Finance": "enforce",       # Access to billing, financial data
    "HR": "enforce",            # Access to compensation, PII
    "Engineering": "allow",     # Balance security with developer productivity
    "Data": "allow",            # Balance security with productivity
    "Product": "allow",
    "Design": "allow",
    "Sales": "allow",
    "Marketing": "allow",
}


def get_directory_service(admin_email: str):
    """Get Admin SDK Directory service for OU lookups."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=ADMIN_SDK_SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def get_cloud_identity_credentials(admin_email: str):
    """Get Cloud Identity API credentials with domain-wide delegation."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=CLOUD_IDENTITY_SCOPES,
        subject=admin_email,
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials


def get_ou_ids(directory_service):
    """Fetch OU name → OU ID mapping (strips 'id:' prefix for API compatibility)."""
    result = directory_service.orgunits().list(customerId=CUSTOMER_ID).execute()
    ou_map = {}
    for ou in result.get("organizationUnits", []):
        # Admin SDK returns "id:03ph8a2z..." but Policy API expects just "03ph8a2z..."
        ou_id = ou["orgUnitId"].replace("id:", "")
        ou_map[ou["name"]] = ou_id
    return ou_map


def list_existing_policies(credentials, customer_id, setting_type):
    """List existing policies for a given setting type using REST API."""
    import requests

    url = "https://cloudidentity.googleapis.com/v1beta1/policies"
    headers = {"Authorization": f"Bearer {credentials.token}"}
    params = {
        "pageSize": 100,
        "filter": f'customer == "customers/{customer_id}" && setting.type == "{setting_type}"',
    }
    resp = requests.get(url, headers=headers, params=params)
    if resp.status_code == 200:
        return resp.json().get("policies", [])
    elif resp.status_code == 404:
        return []
    else:
        print(f"  Warning: list policies returned {resp.status_code}: {resp.text[:200]}")
        return []


def create_or_update_policy(credentials, customer_id, ou_id, setting_type, setting_value, dry_run=False):
    """Create a policy for a specific OU using the v1beta1 REST API."""
    import requests

    if dry_run:
        return True

    # Format must match existing policies:
    # - customer: "customers/{customer_id}"
    # - orgUnit: "orgUnits/{ou_id}"
    # - query uses org_unit (underscore)
    # - setting.type prefixed with "settings/"
    policy_body = {
        "customer": f"customers/{customer_id}",
        "policyQuery": {
            "query": f"entity.org_units.exists(org_unit, org_unit.org_unit_id == orgUnitId('{ou_id}'))",
            "orgUnit": f"orgUnits/{ou_id}",
        },
        "setting": {
            "type": f"settings/{setting_type}",
            "value": setting_value,
        },
    }

    url = "https://cloudidentity.googleapis.com/v1beta1/policies"
    headers = {
        "Authorization": f"Bearer {credentials.token}",
        "Content-Type": "application/json",
    }
    resp = requests.post(url, headers=headers, json=policy_body)

    if resp.status_code in (200, 201):
        return True
    elif resp.status_code == 409:
        # Policy already exists
        return True
    else:
        print(f"  API error {resp.status_code}: {resp.text[:300]}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Configure per-OU 2-Step Verification policies"
    )
    parser.add_argument("--admin-email", default=os.getenv("GWS_ADMIN_EMAIL"), help="Admin email to impersonate (default: GWS_ADMIN_EMAIL from .env)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating")
    args = parser.parse_args()

    print("Per-OU 2-Step Verification Configuration")
    print(f"Admin: {args.admin_email}")
    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***\n")

    # Get OU IDs via Admin SDK
    directory_service = get_directory_service(args.admin_email)
    ou_map = get_ou_ids(directory_service)
    print(f"Found {len(ou_map)} OUs\n")

    # Get Cloud Identity credentials
    ci_credentials = get_cloud_identity_credentials(args.admin_email)

    # Get actual customer ID by listing any existing policy
    import requests
    resp = requests.get(
        "https://cloudidentity.googleapis.com/v1beta1/policies",
        headers={"Authorization": f"Bearer {ci_credentials.token}"},
        params={"pageSize": 1},
    )
    if resp.status_code == 200 and resp.json().get("policies"):
        # Extract customer ID from existing policy (format: "customers/{id}")
        actual_customer_id = resp.json()["policies"][0]["customer"].replace("customers/", "")
    else:
        print("ERROR: Could not determine customer ID from existing policies.")
        print("Ensure at least one policy exists (e.g., configure IT-Ops 2SV via Admin Console first).")
        sys.exit(1)
    print(f"Customer ID: {actual_customer_id}\n")

    # Configure each OU
    success = 0
    failed = 0

    for ou_name, policy_level in TWO_SV_POLICIES.items():
        ou_id = ou_map.get(ou_name)
        if not ou_id:
            print(f"  SKIP: OU '{ou_name}' not found")
            failed += 1
            continue

        if policy_level == "enforce":
            enrollment_value = {"allowEnrollment": True}
            enforcement_value = {"enforcedFrom": "2026-04-06T00:00:00Z"}
            label = "ENFORCE"
        else:
            enrollment_value = {"allowEnrollment": True}
            enforcement_value = None
            label = "ALLOW"

        if args.dry_run:
            print(f"  [DRY RUN] {ou_name} ({ou_id}): {label}")
            success += 1
            continue

        # Set enrollment policy (allow 2SV enrollment)
        print(f"  Setting {ou_name}: {label}")
        result = create_or_update_policy(
            ci_credentials,
            actual_customer_id,
            ou_id,
            "security.two_step_verification_enrollment",
            enrollment_value,
            args.dry_run,
        )

        # Set enforcement policy if enforcing
        if enforcement_value and result:
            result = create_or_update_policy(
                ci_credentials,
                actual_customer_id,
                ou_id,
                "security.two_step_verification_enforcement",
                enforcement_value,
                args.dry_run,
            )

        if result:
            print(f"  ✓ {ou_name}: {label}")
            success += 1
        else:
            print(f"  ✗ {ou_name}: FAILED")
            failed += 1

    # Summary
    print(f"\n{'=' * 50}")
    print(f"2-STEP VERIFICATION CONFIGURATION COMPLETE")
    print(f"  Configured: {success}")
    print(f"  Failed:     {failed}")
    print(f"  Total:      {success + failed}")
    print(f"\nPolicy summary:")
    for ou_name, policy_level in sorted(TWO_SV_POLICIES.items()):
        icon = "🔒" if policy_level == "enforce" else "🔓"
        print(f"  {icon} {ou_name}: {policy_level.upper()}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
