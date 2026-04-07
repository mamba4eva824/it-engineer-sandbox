#!/usr/bin/env python3
"""
Auth0 → GWS Sync: Department-based OU Placement

Reads user department metadata from Auth0 (source of truth) and ensures
each user is in the correct Google Cloud Identity OU. Detects and optionally
remediates drift — users whose GWS OU doesn't match their Auth0 department.

This is SCIM-like provisioning from the application side: Auth0 owns the
user attributes, and GWS OU placement is derived from them.

Prerequisites:
  1. pip install auth0-python google-auth google-api-python-client python-dotenv
  2. Auth0 M2M credentials in .env (AUTH0_DOMAIN, AUTH0_CLIENT_ID, AUTH0_CLIENT_SECRET)
  3. GWS service account with domain-wide delegation (GWS_SERVICE_ACCOUNT_KEY, GWS_ADMIN_EMAIL in .env)
  4. Users must exist in both Auth0 and GWS with matching email domains

Usage:
  python sync_auth0_gws.py --dry-run    # Report drift only (uses .env)
  python sync_auth0_gws.py              # Detect + remediate
  python sync_auth0_gws.py --report     # Generate drift report
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

# --- Configuration ---

SERVICE_ACCOUNT_KEY = Path(__file__).parent.parent.parent / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
GWS_DOMAIN = os.getenv("GWS_DOMAIN", "example.com")
GWS_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user"]
CUSTOMER_ID = "my_customer"

# Valid department → OU mapping (Auth0 department name → GWS OU path)
DEPARTMENT_TO_OU = {
    "Engineering": "/Engineering",
    "IT-Ops": "/IT-Ops",
    "Finance": "/Finance",
    "Executive": "/Executive",
    "Data": "/Data",
    "Product": "/Product",
    "Design": "/Design",
    "HR": "/HR",
    "Sales": "/Sales",
    "Marketing": "/Marketing",
}


def get_auth0_client():
    """Authenticate and return an Auth0 Management API client."""
    from auth0.management import Auth0
    from auth0.authentication import GetToken

    domain = os.getenv("AUTH0_DOMAIN")
    client_id = os.getenv("AUTH0_CLIENT_ID")
    client_secret = os.getenv("AUTH0_CLIENT_SECRET")

    if not all([domain, client_id, client_secret]):
        print("ERROR: Missing Auth0 credentials in .env file.")
        sys.exit(1)

    get_token = GetToken(domain, client_id, client_secret=client_secret)
    token = get_token.client_credentials(f"https://{domain}/api/v2/")
    return Auth0(tenant_domain=domain, token=token["access_token"])


def get_gws_service(admin_email: str):
    """Authenticate via service account with domain-wide delegation."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=GWS_SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def fetch_auth0_users(auth0_client):
    """Fetch all Auth0 users with department metadata. Returns {email: department}."""
    users = {}
    page = 0
    per_page = 100
    while True:
        result = auth0_client.users.list(
            page=page,
            per_page=per_page,
            fields="email,user_metadata",
        )
        # auth0-python v5 returns SyncPager; extract users list
        if hasattr(result, "items"):
            batch = list(result.items)
        elif isinstance(result, dict):
            batch = result.get("users", [])
        else:
            batch = list(result)
        if not batch:
            break
        for u in batch:
            email = (u.get("email") if isinstance(u, dict) else getattr(u, "email", "")) or ""
            email = email.lower()
            if isinstance(u, dict):
                department = u.get("user_metadata", {}).get("department", "Unknown")
            else:
                metadata = getattr(u, "user_metadata", {}) or {}
                department = metadata.get("department", "Unknown")
            if email:
                users[email] = department
        if len(batch) < per_page:
            break
        page += 1
    return users


def fetch_gws_users(gws_service):
    """Fetch all GWS users with OU placement. Returns {email: orgUnitPath}."""
    users = {}
    page_token = None
    while True:
        result = gws_service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields="users(primaryEmail,orgUnitPath),nextPageToken",
        ).execute()
        for u in result.get("users", []):
            email = u["primaryEmail"].lower()
            ou_path = u.get("orgUnitPath", "/")
            users[email] = ou_path
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return users


def detect_drift(auth0_users, gws_users):
    """Compare Auth0 departments to GWS OU placements. Returns list of drift entries."""
    drift = []

    for email, department in auth0_users.items():
        expected_ou = DEPARTMENT_TO_OU.get(department)
        if not expected_ou:
            drift.append({
                "email": email,
                "auth0_department": department,
                "expected_ou": "UNKNOWN",
                "actual_ou": gws_users.get(email, "NOT IN GWS"),
                "action": "REVIEW — unknown department",
            })
            continue

        if email not in gws_users:
            drift.append({
                "email": email,
                "auth0_department": department,
                "expected_ou": expected_ou,
                "actual_ou": "NOT IN GWS",
                "action": "PROVISION — user exists in Auth0 but not GWS",
            })
            continue

        actual_ou = gws_users[email]
        if actual_ou != expected_ou:
            drift.append({
                "email": email,
                "auth0_department": department,
                "expected_ou": expected_ou,
                "actual_ou": actual_ou,
                "action": f"MOVE — OU mismatch",
            })

    # Check for orphaned GWS users (in GWS but not Auth0)
    for email, ou_path in gws_users.items():
        if email not in auth0_users:
            drift.append({
                "email": email,
                "auth0_department": "NOT IN AUTH0",
                "expected_ou": "N/A",
                "actual_ou": ou_path,
                "action": "ORPHAN — user exists in GWS but not Auth0",
            })

    return drift


def remediate_drift(gws_service, drift_entries, dry_run=False):
    """Move users to correct OUs based on drift detection."""
    moved = 0
    skipped = 0
    failed = 0

    for entry in drift_entries:
        if entry["action"].startswith("MOVE"):
            email = entry["email"]
            target_ou = entry["expected_ou"]

            if dry_run:
                print(f"  [DRY RUN] Would move {email}: {entry['actual_ou']} -> {target_ou}")
                moved += 1
                continue

            try:
                gws_service.users().update(
                    userKey=email,
                    body={"orgUnitPath": target_ou},
                ).execute()
                print(f"  MOVED: {email}: {entry['actual_ou']} -> {target_ou}")
                moved += 1
            except HttpError as e:
                print(f"  FAILED: {email} — {e}")
                failed += 1
        else:
            skipped += 1

    return moved, skipped, failed


def generate_report(auth0_users, gws_users, drift_entries):
    """Generate a drift report as markdown."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# Auth0 → GWS Sync Report",
        f"\n**Generated:** {timestamp}",
        f"**Auth0 users:** {len(auth0_users)}",
        f"**GWS users:** {len(gws_users)}",
        f"**Drift entries:** {len(drift_entries)}",
        "",
    ]

    if not drift_entries:
        lines.append("**No drift detected.** All GWS users are in the correct OU based on Auth0 department metadata.")
    else:
        # Categorize drift
        moves = [d for d in drift_entries if d["action"].startswith("MOVE")]
        provisions = [d for d in drift_entries if d["action"].startswith("PROVISION")]
        orphans = [d for d in drift_entries if d["action"].startswith("ORPHAN")]
        reviews = [d for d in drift_entries if d["action"].startswith("REVIEW")]

        lines.append("## Summary\n")
        lines.append(f"| Category | Count |")
        lines.append(f"|----------|-------|")
        lines.append(f"| OU Mismatches (need move) | {len(moves)} |")
        lines.append(f"| Missing from GWS (need provisioning) | {len(provisions)} |")
        lines.append(f"| Orphaned in GWS (not in Auth0) | {len(orphans)} |")
        lines.append(f"| Unknown department (need review) | {len(reviews)} |")

        if moves:
            lines.append("\n## OU Mismatches\n")
            lines.append("| Email | Auth0 Department | Expected OU | Actual OU |")
            lines.append("|-------|-----------------|-------------|-----------|")
            for d in moves:
                lines.append(f"| {d['email']} | {d['auth0_department']} | {d['expected_ou']} | {d['actual_ou']} |")

        if provisions:
            lines.append("\n## Missing from GWS\n")
            lines.append("| Email | Auth0 Department | Expected OU |")
            lines.append("|-------|-----------------|-------------|")
            for d in provisions:
                lines.append(f"| {d['email']} | {d['auth0_department']} | {d['expected_ou']} |")

        if orphans:
            lines.append("\n## Orphaned GWS Users\n")
            lines.append("| Email | GWS OU |")
            lines.append("|-------|--------|")
            for d in orphans:
                lines.append(f"| {d['email']} | {d['actual_ou']} |")

    lines.append("\n---")
    lines.append(f"\n*Report generated by `scripts/lifecycle/sync_auth0_gws.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Sync Auth0 departments to GWS OU placement"
    )
    parser.add_argument("--admin-email", default=os.getenv("GWS_ADMIN_EMAIL"), help="GWS admin email to impersonate (default: GWS_ADMIN_EMAIL from .env)")
    parser.add_argument("--dry-run", action="store_true", help="Report drift without remediating")
    parser.add_argument("--report", action="store_true", help="Generate markdown drift report")
    args = parser.parse_args()

    print("Auth0 → GWS Sync: Department-based OU Placement")
    print(f"GWS Admin: {args.admin_email}")
    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***")
    print()

    # Connect to both platforms
    print("Connecting to Auth0 Management API...")
    auth0_client = get_auth0_client()

    print("Connecting to GWS Directory API...")
    gws_service = get_gws_service(args.admin_email)

    # Fetch users from both platforms
    print("Fetching Auth0 users...")
    auth0_users = fetch_auth0_users(auth0_client)
    print(f"  Found {len(auth0_users)} Auth0 users with @{GWS_DOMAIN} emails")

    print("Fetching GWS users...")
    gws_users = fetch_gws_users(gws_service)
    print(f"  Found {len(gws_users)} GWS users")
    print()

    # Detect drift
    print("Detecting drift...")
    drift_entries = detect_drift(auth0_users, gws_users)

    if not drift_entries:
        print("  No drift detected — all users in correct OUs.")
    else:
        moves = [d for d in drift_entries if d["action"].startswith("MOVE")]
        provisions = [d for d in drift_entries if d["action"].startswith("PROVISION")]
        orphans = [d for d in drift_entries if d["action"].startswith("ORPHAN")]

        print(f"  Drift detected:")
        if moves:
            print(f"    OU mismatches: {len(moves)}")
        if provisions:
            print(f"    Missing from GWS: {len(provisions)}")
        if orphans:
            print(f"    Orphaned in GWS: {len(orphans)}")
    print()

    # Remediate OU mismatches
    if drift_entries:
        moves = [d for d in drift_entries if d["action"].startswith("MOVE")]
        if moves:
            print("Remediating OU mismatches...")
            moved, skipped, failed = remediate_drift(
                gws_service, drift_entries, args.dry_run
            )
            print(f"  Moved: {moved}, Skipped: {skipped}, Failed: {failed}")
            print()

    # Generate report
    if args.report:
        report = generate_report(auth0_users, gws_users, drift_entries)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"drift-report-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"Drift report saved to: {report_path}")
        print()

    # Summary
    print(f"{'=' * 50}")
    print("SYNC COMPLETE")
    print(f"  Auth0 users:    {len(auth0_users)}")
    print(f"  GWS users:      {len(gws_users)}")
    print(f"  Drift entries:  {len(drift_entries)}")
    print(f"{'=' * 50}")


if __name__ == "__main__":
    main()
