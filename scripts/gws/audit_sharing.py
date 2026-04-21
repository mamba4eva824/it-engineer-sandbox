#!/usr/bin/env python3
"""
Drive Sharing Audit for Google Workspace.

For each user in the tenant, impersonates them (via domain-wide delegation)
and enumerates files they own, flagging over-exposed sharing:

  - EXTERNAL: shared with a user outside the tenant domain
  - ANYONE:   "anyone with the link" / public links
  - DOMAIN:   domain-wide sharing inside the tenant (baseline; informational)
  - WRITER+:  external parties with edit/comment rights (higher severity)

Aggregates findings by OU so you can see which departments have the most
external exposure — the compartmentalization story for data governance.

Prerequisites:
  1. pip install -r requirements.txt
  2. Service account with domain-wide delegation
  3. New scopes authorized in Admin Console > Domain-wide delegation:
       https://www.googleapis.com/auth/drive.metadata.readonly

Usage:
  python audit_sharing.py                    # Uses GWS_ADMIN_EMAIL from .env
  python audit_sharing.py --report           # Write markdown report
  python audit_sharing.py --user alice@ohmgym.com   # Audit one user only
  python audit_sharing.py --limit 50         # Limit files per user (smoke test)
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

DIRECTORY_SCOPES = ["https://www.googleapis.com/auth/admin.directory.user"]
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.metadata.readonly"]

FILE_FIELDS = (
    "nextPageToken,"
    "files(id,name,mimeType,owners(emailAddress),"
    "webViewLink,modifiedTime,"
    "permissions(id,type,role,emailAddress,domain,allowFileDiscovery))"
)


def get_directory_service(admin_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=DIRECTORY_SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def get_drive_service_for(user_email: str):
    """Impersonate a specific user to list their Drive files."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=DRIVE_SCOPES,
        subject=user_email,
    )
    return build("drive", "v3", credentials=credentials)


def fetch_all_users(service):
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


def list_user_files(drive_service, limit=None):
    """List all files owned by the impersonated user, with permission detail."""
    files = []
    page_token = None
    # q filter: only files where the user is an owner (skip shared-to-me)
    query = "'me' in owners and trashed = false"
    while True:
        result = drive_service.files().list(
            q=query,
            pageSize=200,
            pageToken=page_token,
            fields=FILE_FIELDS,
            corpora="user",
        ).execute()
        batch = result.get("files", [])
        files.extend(batch)
        if limit and len(files) >= limit:
            return files[:limit]
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return files


def classify_permission(perm: dict, domain: str) -> list[str]:
    """Return a list of exposure tags for a single permission entry."""
    tags = []
    ptype = perm.get("type", "")
    role = perm.get("role", "reader")
    email = (perm.get("emailAddress") or "").lower()
    pdomain = (perm.get("domain") or "").lower()
    allow_discovery = perm.get("allowFileDiscovery", False)

    if ptype == "anyone":
        tag = "ANYONE_PUBLIC" if allow_discovery else "ANYONE_LINK"
        tags.append(tag)
    elif ptype == "domain":
        if pdomain and pdomain != domain:
            tags.append("EXTERNAL_DOMAIN")
        else:
            tags.append("DOMAIN_INTERNAL")
    elif ptype == "user":
        if email and not email.endswith(f"@{domain}"):
            tags.append("EXTERNAL_USER")
    elif ptype == "group":
        if email and not email.endswith(f"@{domain}"):
            tags.append("EXTERNAL_GROUP")

    # Add writer/owner severity marker
    if tags and role in ("writer", "owner", "commenter", "fileOrganizer", "organizer"):
        tags.append(f"ROLE_{role.upper()}")

    return tags


def audit_file(file_obj: dict, owner_email: str, owner_ou: str) -> dict | None:
    """Return a finding dict if the file has risky sharing, else None."""
    findings = []
    for perm in file_obj.get("permissions", []) or []:
        tags = classify_permission(perm, GWS_DOMAIN)
        risky = [t for t in tags if t.startswith(("ANYONE", "EXTERNAL"))]
        if risky:
            findings.append({
                "perm_type": perm.get("type"),
                "role": perm.get("role"),
                "email": perm.get("emailAddress"),
                "domain": perm.get("domain"),
                "allow_discovery": perm.get("allowFileDiscovery", False),
                "tags": tags,
            })

    if not findings:
        return None

    return {
        "file_id": file_obj["id"],
        "name": file_obj["name"],
        "mime": file_obj.get("mimeType", ""),
        "link": file_obj.get("webViewLink", ""),
        "owner": owner_email,
        "ou": owner_ou,
        "modified": file_obj.get("modifiedTime", ""),
        "findings": findings,
    }


def audit_tenant(directory_service, user_filter=None, limit=None):
    """Walk all users and return a list of risky-sharing findings."""
    users = fetch_all_users(directory_service)
    if user_filter:
        users = [u for u in users if u["primaryEmail"].lower() == user_filter.lower()]

    all_findings = []
    per_user_stats = []

    for u in users:
        email = u["primaryEmail"]
        ou = u.get("orgUnitPath", "/")
        if u.get("suspended"):
            continue

        print(f"  {email} ({ou})")
        try:
            drive = get_drive_service_for(email)
            files = list_user_files(drive, limit=limit)
        except HttpError as e:
            print(f"    FAILED: {e}")
            continue
        except Exception as e:
            print(f"    FAILED: {e}")
            continue

        user_findings = []
        for f in files:
            finding = audit_file(f, email, ou)
            if finding:
                user_findings.append(finding)

        print(f"    {len(files)} files, {len(user_findings)} risky")
        all_findings.extend(user_findings)
        per_user_stats.append({
            "email": email,
            "ou": ou,
            "file_count": len(files),
            "risky_count": len(user_findings),
        })

    return all_findings, per_user_stats


def generate_report(findings, per_user_stats):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    by_ou = defaultdict(lambda: {"files": 0, "risky": 0, "findings": []})
    for s in per_user_stats:
        by_ou[s["ou"]]["files"] += s["file_count"]
        by_ou[s["ou"]]["risky"] += s["risky_count"]
    for f in findings:
        by_ou[f["ou"]]["findings"].append(f)

    by_tag = defaultdict(int)
    for f in findings:
        for finding in f["findings"]:
            for t in finding["tags"]:
                by_tag[t] += 1

    total_files = sum(s["file_count"] for s in per_user_stats)

    lines = [
        "# Drive Sharing Audit — Data Governance",
        f"\n**Generated:** {timestamp}",
        f"**Tenant domain:** {GWS_DOMAIN}",
        f"**Users scanned:** {len(per_user_stats)}",
        f"**Files inspected:** {total_files}",
        f"**Risky files found:** {len(findings)}",
        "",
        "## Exposure Breakdown",
        "",
        "| Exposure Tag | Count | Meaning |",
        "|--------------|-------|---------|",
        f"| ANYONE_PUBLIC  | {by_tag['ANYONE_PUBLIC']}  | Public link, discoverable via search |",
        f"| ANYONE_LINK    | {by_tag['ANYONE_LINK']}    | Anyone with the link (unlisted) |",
        f"| EXTERNAL_USER  | {by_tag['EXTERNAL_USER']}  | Specific user outside the tenant |",
        f"| EXTERNAL_GROUP | {by_tag['EXTERNAL_GROUP']} | External group |",
        f"| EXTERNAL_DOMAIN | {by_tag['EXTERNAL_DOMAIN']} | Entire external domain |",
        "",
        "## Per-OU Summary",
        "",
        "| OU | Files Scanned | Risky Files |",
        "|----|---------------|-------------|",
    ]
    for ou in sorted(by_ou.keys()):
        d = by_ou[ou]
        lines.append(f"| {ou} | {d['files']} | {d['risky']} |")
    lines.append("")

    if findings:
        lines.append("## Risky Files (Detail)\n")
        for f in findings:
            lines.append(f"### {f['name']}")
            lines.append(f"- **Owner:** {f['owner']} ({f['ou']})")
            lines.append(f"- **Link:** [{f['file_id']}]({f['link']})")
            lines.append(f"- **Modified:** {f['modified']}")
            lines.append("- **Findings:**")
            for finding in f["findings"]:
                tag_str = ", ".join(finding["tags"])
                target = finding.get("email") or finding.get("domain") or "anyone"
                lines.append(
                    f"  - [{tag_str}] {finding['perm_type']} → {target} (role: {finding['role']})"
                )
            lines.append("")
    else:
        lines.append("## Findings\n")
        lines.append("**No risky sharing detected.** All files owned by scanned users are internal-only.")
        lines.append("")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/gws/audit_sharing.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Audit Drive sharing for over-exposed files"
    )
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate for user listing",
    )
    parser.add_argument("--user", help="Audit a single user only")
    parser.add_argument("--limit", type=int, help="Limit files per user (for smoke tests)")
    parser.add_argument("--report", action="store_true", help="Write markdown report")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    print("Drive Sharing Audit")
    print(f"Tenant domain: {GWS_DOMAIN}")
    print(f"Admin: {args.admin_email}\n")

    directory_service = get_directory_service(args.admin_email)
    print("Connected to Admin SDK Directory API\n")

    print("Walking user Drives (impersonated)...")
    findings, per_user_stats = audit_tenant(
        directory_service, user_filter=args.user, limit=args.limit
    )

    # Summary
    total_files = sum(s["file_count"] for s in per_user_stats)
    print(f"\n{'=' * 60}")
    print("DRIVE SHARING AUDIT COMPLETE")
    print(f"  Users scanned:    {len(per_user_stats)}")
    print(f"  Files inspected:  {total_files}")
    print(f"  Risky files:      {len(findings)}")
    print(f"{'=' * 60}")

    if args.report:
        report = generate_report(findings, per_user_stats)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"sharing-audit-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
