#!/usr/bin/env python3
"""
Third-Party App Governance Audit for Google Workspace.

Enumerates every OAuth grant in the tenant (per-user via Tokens API) and
categorizes each app by the sensitivity of the scopes it was granted.
Produces a risk-tiered report suitable for a quarterly app review.

Risk tiers (by most-sensitive scope granted):
  - HIGH:    Admin, Drive, Gmail, Cloud Identity, or wildcard scopes
  - MEDIUM:  Calendar, Contacts, Groups, Reports
  - LOW:     profile, email, openid, or other read-only metadata

Prerequisites:
  1. pip install -r requirements.txt
  2. Cloud Identity/Workspace service account with domain-wide delegation
  3. OAuth scope granted to the service account:
       https://www.googleapis.com/auth/admin.directory.user.security
       https://www.googleapis.com/auth/admin.directory.user.readonly

Usage:
  python audit_apps.py                       # Uses GWS_ADMIN_EMAIL from .env
  python audit_apps.py --report              # Also write markdown report
  python audit_apps.py --risk HIGH           # Filter output to HIGH-risk apps
  python audit_apps.py --revoke-client <id>  # Revoke an app tenant-wide (destructive; requires confirmation)
"""

import argparse
import json
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

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.user.security",
    "https://www.googleapis.com/auth/admin.directory.user",
]

# Risk tiering by scope substring match. Most-sensitive match wins.
HIGH_RISK_SCOPE_PATTERNS = [
    "admin",                     # any admin.* scope (directory, reports, groups)
    "drive",                     # drive, drive.file, drive.metadata, drive.readonly
    "gmail",                     # full Gmail API
    "mail.google.com",           # legacy Gmail full-access
    "cloud-identity",            # directory writes
    "cloud-platform",            # full GCP
    "apps.groups.settings",      # group settings writes
]
# Short exact-match scopes that don't trigger pattern matching
LOW_RISK_EXACT = {
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
}
MEDIUM_RISK_SCOPE_PATTERNS = [
    "calendar",
    "contacts",
    "groups",
    "reports",
    "tasks",
    "docs",
    "spreadsheets",
    "presentations",
    "classroom",
    "meetings",
]


def classify_scope(scope: str) -> str:
    """Return HIGH, MEDIUM, or LOW for a single scope string."""
    s = scope.lower()
    if scope in LOW_RISK_EXACT or s in LOW_RISK_EXACT:
        return "LOW"
    # HIGH wins over MEDIUM if both patterns match
    for pat in HIGH_RISK_SCOPE_PATTERNS:
        if pat in s:
            return "HIGH"
    for pat in MEDIUM_RISK_SCOPE_PATTERNS:
        if pat in s:
            return "MEDIUM"
    return "LOW"


def classify_app(scopes: list[str]) -> str:
    """Return the worst (most-sensitive) risk tier across all scopes for an app."""
    tiers = {classify_scope(s) for s in scopes}
    if "HIGH" in tiers:
        return "HIGH"
    if "MEDIUM" in tiers:
        return "MEDIUM"
    return "LOW"


def get_directory_service(admin_email: str):
    """Service-account-with-delegation auth pattern used across scripts/gws/."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def fetch_all_users(service):
    """Return [{primaryEmail, orgUnitPath}] for every user in the tenant."""
    users = []
    page_token = None
    while True:
        result = service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields="users(primaryEmail,orgUnitPath,suspended),nextPageToken",
        ).execute()
        users.extend(result.get("users", []))
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return users


def fetch_tokens_for_user(service, user_email):
    """Return list of OAuth tokens currently valid for a user."""
    try:
        result = service.tokens().list(userKey=user_email).execute()
        return result.get("items", [])
    except HttpError as e:
        # 404 = user has no tokens; 403 = insufficient scope
        if e.resp.status == 404:
            return []
        print(f"  WARN: {user_email} tokens fetch failed — {e}")
        return []


def revoke_app_tenant_wide(service, users, client_id, dry_run=False):
    """Revoke a given OAuth client across all users. Destructive."""
    revoked = 0
    failed = 0
    for u in users:
        email = u["primaryEmail"]
        if dry_run:
            print(f"  [DRY RUN] Would revoke {client_id} for {email}")
            revoked += 1
            continue
        try:
            service.tokens().delete(userKey=email, clientId=client_id).execute()
            print(f"  Revoked: {email}")
            revoked += 1
        except HttpError as e:
            if e.resp.status == 404:
                # User never granted it — skip silently
                continue
            print(f"  FAILED: {email} — {e}")
            failed += 1
    return revoked, failed


def aggregate_by_app(users, service):
    """Walk all users' tokens and return {client_id: {...app details...}}."""
    apps = {}
    for u in users:
        email = u["primaryEmail"]
        ou = u.get("orgUnitPath", "/")
        tokens = fetch_tokens_for_user(service, email)
        for t in tokens:
            client_id = t.get("clientId", "unknown")
            display_name = t.get("displayText", client_id)
            scopes = t.get("scopes", [])
            anon = t.get("anonymous", False)
            native_app = t.get("nativeApp", False)

            if client_id not in apps:
                apps[client_id] = {
                    "client_id": client_id,
                    "display_name": display_name,
                    "scopes": set(),
                    "users": [],
                    "ous": set(),
                    "anonymous": anon,
                    "native_app": native_app,
                }
            apps[client_id]["scopes"].update(scopes)
            apps[client_id]["users"].append(email)
            apps[client_id]["ous"].add(ou)

    # Finalize: convert sets, classify risk
    finalized = []
    for client_id, data in apps.items():
        scopes = sorted(data["scopes"])
        risk = classify_app(scopes)
        finalized.append({
            "client_id": client_id,
            "display_name": data["display_name"],
            "risk": risk,
            "scope_count": len(scopes),
            "scopes": scopes,
            "user_count": len(data["users"]),
            "users": sorted(data["users"]),
            "ous": sorted(data["ous"]),
            "anonymous": data["anonymous"],
            "native_app": data["native_app"],
        })
    # HIGH first, then by user_count desc
    risk_rank = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    finalized.sort(key=lambda a: (risk_rank[a["risk"]], -a["user_count"], a["display_name"].lower()))
    return finalized


def print_summary(apps, risk_filter=None):
    """Pretty-print aggregated app audit to stdout."""
    shown = apps if not risk_filter else [a for a in apps if a["risk"] == risk_filter]
    by_risk = defaultdict(int)
    for a in apps:
        by_risk[a["risk"]] += 1

    print(f"\n{'=' * 70}")
    print("THIRD-PARTY APP AUDIT")
    print(f"{'=' * 70}")
    print(f"  Total unique apps:  {len(apps)}")
    print(f"  HIGH risk:          {by_risk['HIGH']}")
    print(f"  MEDIUM risk:        {by_risk['MEDIUM']}")
    print(f"  LOW risk:           {by_risk['LOW']}")
    if risk_filter:
        print(f"  (filtered to {risk_filter} only — {len(shown)} shown)")
    print(f"{'=' * 70}\n")

    for a in shown:
        print(f"  [{a['risk']}] {a['display_name']}")
        print(f"       client_id: {a['client_id']}")
        print(f"       users:     {a['user_count']} ({', '.join(a['ous'])})")
        print(f"       scopes:    {a['scope_count']}")
        for s in a["scopes"][:5]:
            print(f"         - {s}")
        if len(a["scopes"]) > 5:
            print(f"         ... and {len(a['scopes']) - 5} more")
        print()


def generate_report(apps, users):
    """Markdown report for docs/reports/."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    by_risk = defaultdict(list)
    for a in apps:
        by_risk[a["risk"]].append(a)

    lines = [
        "# Third-Party App Governance Audit",
        f"\n**Generated:** {timestamp}",
        f"**Tenant users scanned:** {len(users)}",
        f"**Unique third-party apps:** {len(apps)}",
        "",
        "## Risk Distribution",
        "",
        "| Risk Tier | Count | Definition |",
        "|-----------|-------|------------|",
        f"| HIGH   | {len(by_risk['HIGH'])}   | Grants Admin, Drive, Gmail, or Cloud Identity scopes |",
        f"| MEDIUM | {len(by_risk['MEDIUM'])} | Grants Calendar, Contacts, Groups, Docs, or similar |",
        f"| LOW    | {len(by_risk['LOW'])}    | Profile/email/openid only |",
        "",
    ]

    for risk in ("HIGH", "MEDIUM", "LOW"):
        entries = by_risk[risk]
        if not entries:
            continue
        lines.append(f"## {risk} Risk Apps ({len(entries)})\n")
        lines.append("| App | client_id | Users | OUs | Scopes |")
        lines.append("|-----|-----------|-------|-----|--------|")
        for a in entries:
            ous = ", ".join(a["ous"]) if len(a["ous"]) <= 3 else f"{len(a['ous'])} OUs"
            lines.append(
                f"| {a['display_name']} | `{a['client_id']}` | {a['user_count']} | {ous} | {a['scope_count']} |"
            )
        lines.append("")

    # Scope detail appendix for HIGH-risk apps
    if by_risk["HIGH"]:
        lines.append("## HIGH Risk Scope Detail\n")
        for a in by_risk["HIGH"]:
            lines.append(f"### {a['display_name']}")
            lines.append(f"- **client_id:** `{a['client_id']}`")
            lines.append(f"- **Users ({a['user_count']}):** {', '.join(a['users'])}")
            lines.append(f"- **OUs:** {', '.join(a['ous'])}")
            lines.append("- **Scopes:**")
            for s in a["scopes"]:
                lines.append(f"  - `{s}`")
            lines.append("")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/gws/audit_apps.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Audit third-party OAuth app grants across the tenant"
    )
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate (default: GWS_ADMIN_EMAIL)",
    )
    parser.add_argument("--report", action="store_true", help="Write markdown report to docs/reports/")
    parser.add_argument("--risk", choices=["HIGH", "MEDIUM", "LOW"], help="Filter stdout output to a single tier")
    parser.add_argument("--revoke-client", help="Revoke this OAuth client_id across all users (destructive)")
    parser.add_argument("--dry-run", action="store_true", help="With --revoke-client, preview without revoking")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    print(f"Third-Party App Governance Audit")
    print(f"Admin: {args.admin_email}")

    service = get_directory_service(args.admin_email)
    print("Connected to Admin SDK Directory API")

    print("Fetching tenant users...")
    users = fetch_all_users(service)
    print(f"  Found {len(users)} users\n")

    if args.revoke_client:
        confirm = input(
            f"About to revoke OAuth client '{args.revoke_client}' for {len(users)} users. "
            f"Type 'REVOKE' to continue: "
        )
        if confirm != "REVOKE":
            print("Aborted.")
            sys.exit(0)
        revoked, failed = revoke_app_tenant_wide(service, users, args.revoke_client, args.dry_run)
        print(f"\nRevoked: {revoked}, Failed: {failed}")
        return

    print("Enumerating OAuth grants per user...")
    apps = aggregate_by_app(users, service)

    print_summary(apps, args.risk)

    if args.report:
        report = generate_report(apps, users)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"app-governance-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"Report saved: {report_path}")


if __name__ == "__main__":
    main()
