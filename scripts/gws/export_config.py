#!/usr/bin/env python3
"""
Export the live GWS tenant state to a versioned JSON snapshot.

This is the "config-as-code" export half. Running it produces a single
file (config/gws/desired-state.json) that describes:
  - OU hierarchy (name, parent, description)
  - Users (email, OU placement, organizations metadata, name, manager)
  - Groups (email, name, description) and their members
  - Per-OU security policies (2SV, third-party app access) — from audit_policies desired state

The snapshot is the source of truth that `reconcile_config.py` reads to
detect drift and (optionally) remediate.

Prerequisites:
  1. pip install -r requirements.txt
  2. Service account with domain-wide delegation
  3. Scopes already in use by existing scripts (no new authorization needed):
       admin.directory.orgunit
       admin.directory.user
       admin.directory.group

Usage:
  python export_config.py                 # Writes config/gws/desired-state.json
  python export_config.py --out other.json
  python export_config.py --pretty        # Pretty-print to stdout instead
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

SERVICE_ACCOUNT_KEY = (
    Path(__file__).parent.parent.parent
    / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
)
CUSTOMER_ID = os.getenv("GWS_CUSTOMER_ID", "my_customer")
GWS_DOMAIN = os.getenv("GWS_DOMAIN", "ohmgym.com").lower()

SCOPES = [
    "https://www.googleapis.com/auth/admin.directory.orgunit",
    "https://www.googleapis.com/auth/admin.directory.user",
    "https://www.googleapis.com/auth/admin.directory.group",
]

DEFAULT_OUT = Path(__file__).parent.parent.parent / "config" / "gws" / "desired-state.json"

# Policy desired-state mirror (kept in sync with audit_policies.py & configure_2sv.py)
POLICY_DESIRED_STATE = {
    "IT-Ops":     {"two_step_verification": "ENFORCED",     "third_party_apps": "INHERITED"},
    "Executive":  {"two_step_verification": "ENFORCED",     "third_party_apps": "BLOCK_ALL_SCOPES"},
    "Finance":    {"two_step_verification": "ENFORCED",     "third_party_apps": "BLOCK_ALL_SCOPES"},
    "HR":         {"two_step_verification": "ENFORCED",     "third_party_apps": "BLOCK_ALL_SCOPES"},
    "Engineering": {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
    "Data":       {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
    "Product":    {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
    "Design":     {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
    "Sales":      {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
    "Marketing":  {"two_step_verification": "NOT_ENFORCED", "third_party_apps": "INHERITED"},
}


def get_service(admin_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def export_ous(service):
    result = service.orgunits().list(customerId=CUSTOMER_ID).execute()
    ous = []
    for ou in result.get("organizationUnits", []):
        ous.append({
            "name": ou["name"],
            "orgUnitPath": ou["orgUnitPath"],
            "parentOrgUnitPath": ou.get("parentOrgUnitPath", "/"),
            "description": ou.get("description", ""),
        })
    ous.sort(key=lambda o: o["orgUnitPath"])
    return ous


def export_users(service):
    users = []
    page_token = None
    while True:
        result = service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields=(
                "users(primaryEmail,name,orgUnitPath,suspended,"
                "organizations,relations),nextPageToken"
            ),
        ).execute()
        for u in result.get("users", []):
            primary_org = {}
            for org in u.get("organizations", []) or []:
                if org.get("primary"):
                    primary_org = org
                    break
            manager = None
            for rel in u.get("relations", []) or []:
                if rel.get("type") == "manager":
                    manager = rel.get("value")
                    break
            users.append({
                "primaryEmail": u["primaryEmail"].lower(),
                "givenName": u["name"].get("givenName", ""),
                "familyName": u["name"].get("familyName", ""),
                "orgUnitPath": u.get("orgUnitPath", "/"),
                "suspended": u.get("suspended", False),
                "department": primary_org.get("department", ""),
                "title": primary_org.get("title", ""),
                "costCenter": primary_org.get("costCenter", ""),
                "managerEmail": manager,
            })
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    users.sort(key=lambda u: u["primaryEmail"])
    return users


def export_groups(service):
    groups = []
    page_token = None
    while True:
        result = service.groups().list(
            customer=CUSTOMER_ID,
            maxResults=200,
            pageToken=page_token,
        ).execute()
        for g in result.get("groups", []):
            members = []
            m_token = None
            while True:
                try:
                    m_result = service.members().list(
                        groupKey=g["email"],
                        maxResults=200,
                        pageToken=m_token,
                    ).execute()
                except HttpError as e:
                    if e.resp.status == 404:
                        break
                    raise
                for m in m_result.get("members", []):
                    members.append({
                        "email": (m.get("email") or "").lower(),
                        "role": m.get("role", "MEMBER"),
                        "type": m.get("type", "USER"),
                    })
                m_token = m_result.get("nextPageToken")
                if not m_token:
                    break
            members.sort(key=lambda m: m["email"])
            groups.append({
                "email": g["email"].lower(),
                "name": g.get("name", ""),
                "description": g.get("description", ""),
                "memberCount": len(members),
                "members": members,
            })
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    # Keep only tenant-domain groups (ignore auto-generated)
    groups = [g for g in groups if g["email"].endswith(f"@{GWS_DOMAIN}")]
    groups.sort(key=lambda g: g["email"])
    return groups


def build_snapshot(service):
    snapshot = {
        "schemaVersion": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "domain": GWS_DOMAIN,
        "customerId": CUSTOMER_ID,
        "ous": export_ous(service),
        "users": export_users(service),
        "groups": export_groups(service),
        "policies": POLICY_DESIRED_STATE,
    }
    return snapshot


def main():
    parser = argparse.ArgumentParser(description="Export GWS tenant state to JSON")
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate",
    )
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output path")
    parser.add_argument("--pretty", action="store_true", help="Print to stdout instead of writing")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    print("GWS Tenant Export")
    print(f"Admin: {args.admin_email}\n")

    service = get_service(args.admin_email)
    print("Connected to Admin SDK Directory API")

    print("Exporting OUs...")
    ous = export_ous(service)
    print(f"  {len(ous)} OUs")

    print("Exporting users...")
    users = export_users(service)
    print(f"  {len(users)} users")

    print("Exporting groups (with members)...")
    groups = export_groups(service)
    total_memberships = sum(g["memberCount"] for g in groups)
    print(f"  {len(groups)} groups, {total_memberships} memberships")

    snapshot = {
        "schemaVersion": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "domain": GWS_DOMAIN,
        "customerId": CUSTOMER_ID,
        "ous": ous,
        "users": users,
        "groups": groups,
        "policies": POLICY_DESIRED_STATE,
    }

    if args.pretty:
        print(json.dumps(snapshot, indent=2, default=str))
    else:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w") as f:
            json.dump(snapshot, f, indent=2, default=str)
            f.write("\n")
        print(f"\nSnapshot written: {out_path}")
        print(f"File size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
