#!/usr/bin/env python3
"""
Department-based Google Group lifecycle management.

Turns GWS OU membership into Google Group membership — the same shape as
SCIM group push from an IdP. Creates one group per department, reconciles
members against the current OU state, and reports drift.

Desired state:
  group <dept>@<domain>  <=  every active user whose orgUnitPath == /<Dept>

Modes:
  --create       Create any missing department groups
  --sync         Reconcile membership (add missing members, remove extras)
  --audit        Report drift without making changes
  --dry-run      Preview any mode without writing

Prerequisites:
  1. pip install -r requirements.txt
  2. Service account with domain-wide delegation
  3. Scopes authorized in Admin Console > Domain-wide delegation:
       https://www.googleapis.com/auth/admin.directory.group
       https://www.googleapis.com/auth/admin.directory.user

Usage:
  python manage_groups.py --audit
  python manage_groups.py --create --dry-run
  python manage_groups.py --create
  python manage_groups.py --sync --dry-run
  python manage_groups.py --sync --report
"""

import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

load_dotenv()

# --- Configuration ---

SERVICE_ACCOUNT_KEY = (
    Path(__file__).parent.parent.parent
    / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
)
CUSTOMER_ID = os.getenv("GWS_CUSTOMER_ID", "my_customer")
GWS_DOMAIN = os.getenv("GWS_DOMAIN", "ohmgym.com").lower()

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.group",
    "https://www.googleapis.com/auth/admin.directory.user",
]

# Department name -> group local-part. Group email = {local-part}@{GWS_DOMAIN}
DEPARTMENT_GROUPS = {
    "Engineering": "engineering",
    "IT-Ops": "it-ops",
    "Finance": "finance",
    "Executive": "executive",
    "Data": "data",
    "Product": "product",
    "Design": "design",
    "HR": "hr",
    "Sales": "sales",
    "Marketing": "marketing",
}


def get_service(admin_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def fetch_users_by_ou(service):
    """Return { ou_name (e.g. 'Engineering'): [emails] }, skipping suspended users."""
    by_ou = defaultdict(list)
    page_token = None
    while True:
        result = service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields="users(primaryEmail,orgUnitPath,suspended),nextPageToken",
        ).execute()
        for u in result.get("users", []):
            if u.get("suspended"):
                continue
            ou_path = u.get("orgUnitPath", "/")
            # /Engineering -> Engineering ; ignore root (/)
            if ou_path == "/" or not ou_path.startswith("/"):
                continue
            dept = ou_path[1:].split("/")[0]
            by_ou[dept].append(u["primaryEmail"].lower())
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return by_ou


def fetch_existing_groups(service):
    """Return { group_email: group_id }."""
    existing = {}
    page_token = None
    while True:
        result = service.groups().list(
            customer=CUSTOMER_ID,
            maxResults=200,
            pageToken=page_token,
        ).execute()
        for g in result.get("groups", []):
            existing[g["email"].lower()] = g["id"]
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return existing


def fetch_group_members(service, group_key):
    """Return list of member emails for a group."""
    members = []
    page_token = None
    while True:
        try:
            result = service.members().list(
                groupKey=group_key,
                maxResults=200,
                pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                return []
            raise
        for m in result.get("members", []):
            if m.get("email"):
                members.append(m["email"].lower())
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return members


def create_group(service, email, name, description, dry_run=False):
    if dry_run:
        print(f"  [DRY RUN] Would create group: {email}")
        return True
    try:
        service.groups().insert(body={
            "email": email,
            "name": name,
            "description": description,
        }).execute()
        print(f"  Created: {email}")
        return True
    except HttpError as e:
        if e.resp.status == 409:
            print(f"  Already exists: {email}")
            return True
        print(f"  FAILED to create {email}: {e}")
        return False


def add_member(service, group_email, user_email, dry_run=False):
    if dry_run:
        print(f"    [DRY RUN] + {user_email}")
        return True
    try:
        service.members().insert(
            groupKey=group_email,
            body={"email": user_email, "role": "MEMBER"},
        ).execute()
        print(f"    + {user_email}")
        return True
    except HttpError as e:
        if e.resp.status == 409:
            return True  # already a member
        print(f"    FAILED + {user_email}: {e}")
        return False


def remove_member(service, group_email, user_email, dry_run=False):
    if dry_run:
        print(f"    [DRY RUN] - {user_email}")
        return True
    try:
        service.members().delete(
            groupKey=group_email,
            memberKey=user_email,
        ).execute()
        print(f"    - {user_email}")
        return True
    except HttpError as e:
        print(f"    FAILED - {user_email}: {e}")
        return False


def compute_drift(desired_by_dept, existing_groups, service):
    """
    Compare desired state (OU membership) to actual group membership.
    Returns { dept: {group_email, exists, to_add, to_remove, current_members} }.
    """
    drift = {}
    for dept, local_part in DEPARTMENT_GROUPS.items():
        group_email = f"{local_part}@{GWS_DOMAIN}"
        exists = group_email in existing_groups
        desired_members = set(desired_by_dept.get(dept, []))

        if exists:
            current_members = set(fetch_group_members(service, group_email))
        else:
            current_members = set()

        to_add = desired_members - current_members
        to_remove = current_members - desired_members

        drift[dept] = {
            "group_email": group_email,
            "exists": exists,
            "current_members": sorted(current_members),
            "desired_members": sorted(desired_members),
            "to_add": sorted(to_add),
            "to_remove": sorted(to_remove),
        }
    return drift


def do_create(service, drift, dry_run=False):
    """Create any groups that don't yet exist."""
    created = 0
    skipped = 0
    failed = 0
    for dept, d in drift.items():
        if d["exists"]:
            skipped += 1
            continue
        name = f"NovaTech {dept}"
        description = (
            f"Auto-managed group for NovaTech {dept}. "
            f"Members synced from GWS OU /{dept} via manage_groups.py."
        )
        ok = create_group(service, d["group_email"], name, description, dry_run)
        if ok:
            created += 1
            if not dry_run:
                d["exists"] = True
        else:
            failed += 1
    return created, skipped, failed


def do_sync(service, drift, dry_run=False):
    """Reconcile membership for each group."""
    added = 0
    removed = 0
    failed = 0
    for dept, d in drift.items():
        if not d["exists"]:
            print(f"  SKIP {dept}: group does not exist (run --create first)")
            continue
        if not d["to_add"] and not d["to_remove"]:
            continue
        print(f"  {d['group_email']}:")
        for email in d["to_add"]:
            if add_member(service, d["group_email"], email, dry_run):
                added += 1
            else:
                failed += 1
        for email in d["to_remove"]:
            if remove_member(service, d["group_email"], email, dry_run):
                removed += 1
            else:
                failed += 1
    return added, removed, failed


def print_audit(drift):
    print(f"\n{'=' * 65}")
    print("GROUP MEMBERSHIP AUDIT")
    print(f"{'=' * 65}")
    print(f"{'Group':<35} {'Exists':<8} {'Current':<8} {'Desired':<8} {'Drift'}")
    print("-" * 65)
    total_add = 0
    total_remove = 0
    for dept, d in sorted(drift.items()):
        drift_str = f"+{len(d['to_add'])}/-{len(d['to_remove'])}"
        print(
            f"{d['group_email']:<35} "
            f"{'yes' if d['exists'] else 'NO':<8} "
            f"{len(d['current_members']):<8} "
            f"{len(d['desired_members']):<8} "
            f"{drift_str}"
        )
        total_add += len(d["to_add"])
        total_remove += len(d["to_remove"])
    print(f"\nTotal drift: +{total_add} add, -{total_remove} remove")
    print(f"{'=' * 65}")


def generate_report(drift, mode):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_add = sum(len(d["to_add"]) for d in drift.values())
    total_remove = sum(len(d["to_remove"]) for d in drift.values())
    missing_groups = [dept for dept, d in drift.items() if not d["exists"]]

    lines = [
        "# Google Groups Membership Audit",
        f"\n**Generated:** {timestamp}",
        f"**Mode:** {mode}",
        f"**Tenant domain:** {GWS_DOMAIN}",
        f"**Departments:** {len(DEPARTMENT_GROUPS)}",
        f"**Missing groups:** {len(missing_groups)}",
        f"**Pending adds:** {total_add}",
        f"**Pending removes:** {total_remove}",
        "",
        "## Per-Group Summary",
        "",
        "| Group | Exists | Current | Desired | +Add | -Remove |",
        "|-------|--------|---------|---------|------|---------|",
    ]
    for dept, d in sorted(drift.items()):
        lines.append(
            f"| {d['group_email']} "
            f"| {'yes' if d['exists'] else 'NO'} "
            f"| {len(d['current_members'])} "
            f"| {len(d['desired_members'])} "
            f"| {len(d['to_add'])} "
            f"| {len(d['to_remove'])} |"
        )
    lines.append("")

    for dept, d in sorted(drift.items()):
        if not (d["to_add"] or d["to_remove"]) and d["exists"]:
            continue
        lines.append(f"### {d['group_email']}")
        if not d["exists"]:
            lines.append("- **Status:** MISSING — group needs to be created")
        if d["to_add"]:
            lines.append("- **To add:**")
            for e in d["to_add"]:
                lines.append(f"  - `{e}`")
        if d["to_remove"]:
            lines.append("- **To remove:**")
            for e in d["to_remove"]:
                lines.append(f"  - `{e}`")
        lines.append("")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/gws/manage_groups.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Department-based Google Group lifecycle management"
    )
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--audit", action="store_true", help="Report drift only")
    mode.add_argument("--create", action="store_true", help="Create missing groups")
    mode.add_argument("--sync", action="store_true", help="Reconcile membership")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--report", action="store_true", help="Write markdown report")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    mode_name = "audit" if args.audit else "create" if args.create else "sync"
    print(f"Google Groups Management — mode: {mode_name}")
    print(f"Admin: {args.admin_email}")
    if args.dry_run:
        print("*** DRY RUN MODE — no changes will be made ***")
    print()

    service = get_service(args.admin_email)
    print("Connected to Admin SDK Directory API")

    print("Fetching users by OU...")
    desired_by_dept = fetch_users_by_ou(service)
    total_users = sum(len(v) for v in desired_by_dept.values())
    print(f"  {total_users} users across {len(desired_by_dept)} OUs\n")

    print("Fetching existing groups...")
    existing_groups = fetch_existing_groups(service)
    dept_group_emails = {f"{lp}@{GWS_DOMAIN}" for lp in DEPARTMENT_GROUPS.values()}
    existing_dept_groups = [g for g in existing_groups if g in dept_group_emails]
    print(f"  {len(existing_dept_groups)} of {len(DEPARTMENT_GROUPS)} department groups exist\n")

    print("Computing drift...")
    drift = compute_drift(desired_by_dept, existing_groups, service)

    if args.audit:
        print_audit(drift)
    elif args.create:
        print("Creating missing groups...")
        created, skipped, failed = do_create(service, drift, args.dry_run)
        print(f"\nCreated: {created}, Skipped (already exist): {skipped}, Failed: {failed}")
        # After create, membership will still be empty — suggest next step
        if created and not args.dry_run:
            print("\nNext: run with --sync to populate membership from OUs")
    elif args.sync:
        print("Reconciling membership...")
        added, removed, failed = do_sync(service, drift, args.dry_run)
        print(f"\nAdded: {added}, Removed: {removed}, Failed: {failed}")

    if args.report:
        report = generate_report(drift, mode_name)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"groups-audit-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
