#!/usr/bin/env python3
"""
Reconcile the live GWS tenant against a desired-state JSON snapshot.

Reads config/gws/desired-state.json (produced by export_config.py), pulls
live state from the tenant, and reports drift in four categories:

  - OUs       : missing, extra, or description mismatch
  - Users     : missing, extra, OU placement mismatch, suspended flag
  - Groups    : missing, extra, description mismatch
  - Members   : per-group adds/removes to match desired membership

Modes:
  --audit       Report drift only (default)
  --apply       Remediate drift (create missing OUs/groups, move users, sync members)
  --dry-run     Preview --apply actions without writing

Prerequisites:
  1. pip install -r requirements.txt
  2. Service account with domain-wide delegation; same scopes as export_config.py

Usage:
  python reconcile_config.py                     # audit
  python reconcile_config.py --apply --dry-run   # preview remediation
  python reconcile_config.py --apply             # remediate
  python reconcile_config.py --report            # also write markdown report
  python reconcile_config.py --in config/gws/snapshot.json
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

DEFAULT_IN = Path(__file__).parent.parent.parent / "config" / "gws" / "desired-state.json"


def get_service(admin_email: str):
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def load_desired(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: desired-state file not found: {path}")
        print("Run scripts/gws/export_config.py first to generate it.")
        sys.exit(1)
    with open(path) as f:
        return json.load(f)


# ---------- Live state fetchers (minimal subset needed for reconcile) ----------

def fetch_live_ous(service):
    result = service.orgunits().list(customerId=CUSTOMER_ID).execute()
    return {
        ou["orgUnitPath"]: {
            "name": ou["name"],
            "orgUnitPath": ou["orgUnitPath"],
            "parentOrgUnitPath": ou.get("parentOrgUnitPath", "/"),
            "description": ou.get("description", ""),
        }
        for ou in result.get("organizationUnits", [])
    }


def fetch_live_users(service):
    users = {}
    page_token = None
    while True:
        result = service.users().list(
            customer=CUSTOMER_ID,
            maxResults=500,
            pageToken=page_token,
            fields="users(primaryEmail,orgUnitPath,suspended),nextPageToken",
        ).execute()
        for u in result.get("users", []):
            email = u["primaryEmail"].lower()
            users[email] = {
                "primaryEmail": email,
                "orgUnitPath": u.get("orgUnitPath", "/"),
                "suspended": u.get("suspended", False),
            }
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return users


def fetch_live_groups(service):
    groups = {}
    page_token = None
    while True:
        result = service.groups().list(
            customer=CUSTOMER_ID,
            maxResults=200,
            pageToken=page_token,
        ).execute()
        for g in result.get("groups", []):
            email = g["email"].lower()
            if not email.endswith(f"@{GWS_DOMAIN}"):
                continue
            members = []
            m_token = None
            while True:
                try:
                    m_result = service.members().list(
                        groupKey=email, maxResults=200, pageToken=m_token,
                    ).execute()
                except HttpError as e:
                    if e.resp.status == 404:
                        break
                    raise
                for m in m_result.get("members", []):
                    if m.get("email"):
                        members.append(m["email"].lower())
                m_token = m_result.get("nextPageToken")
                if not m_token:
                    break
            groups[email] = {
                "email": email,
                "name": g.get("name", ""),
                "description": g.get("description", ""),
                "members": set(members),
            }
        page_token = result.get("nextPageToken")
        if not page_token:
            break
    return groups


# ---------- Drift computation ----------

def diff_ous(desired_list, live_map):
    desired_map = {o["orgUnitPath"]: o for o in desired_list}
    missing = [p for p in desired_map if p not in live_map]
    extra = [p for p in live_map if p not in desired_map]
    mismatched = []
    for path in desired_map:
        if path in live_map:
            if desired_map[path].get("description", "") != live_map[path].get("description", ""):
                mismatched.append({
                    "path": path,
                    "desired_description": desired_map[path].get("description", ""),
                    "actual_description": live_map[path].get("description", ""),
                })
    return {"missing": missing, "extra": extra, "mismatched": mismatched, "desired_map": desired_map}


def diff_users(desired_list, live_map):
    desired_map = {u["primaryEmail"]: u for u in desired_list}
    missing = [e for e in desired_map if e not in live_map]
    extra = [e for e in live_map if e not in desired_map]
    ou_mismatch = []
    suspended_mismatch = []
    for email in desired_map:
        if email in live_map:
            d = desired_map[email]
            l = live_map[email]
            if d["orgUnitPath"] != l["orgUnitPath"]:
                ou_mismatch.append({
                    "email": email,
                    "desired_ou": d["orgUnitPath"],
                    "actual_ou": l["orgUnitPath"],
                })
            if bool(d.get("suspended", False)) != bool(l.get("suspended", False)):
                suspended_mismatch.append({
                    "email": email,
                    "desired_suspended": d.get("suspended", False),
                    "actual_suspended": l.get("suspended", False),
                })
    return {
        "missing": missing,
        "extra": extra,
        "ou_mismatch": ou_mismatch,
        "suspended_mismatch": suspended_mismatch,
        "desired_map": desired_map,
    }


def diff_groups(desired_list, live_map):
    desired_map = {g["email"]: g for g in desired_list}
    missing = [e for e in desired_map if e not in live_map]
    extra = [e for e in live_map if e not in desired_map]
    description_mismatch = []
    member_drift = []
    for email in desired_map:
        if email in live_map:
            d = desired_map[email]
            l = live_map[email]
            if d.get("description", "") != l.get("description", ""):
                description_mismatch.append({
                    "email": email,
                    "desired_description": d.get("description", ""),
                    "actual_description": l.get("description", ""),
                })
            desired_members = {m["email"] for m in d.get("members", [])}
            actual_members = l["members"]
            to_add = desired_members - actual_members
            to_remove = actual_members - desired_members
            if to_add or to_remove:
                member_drift.append({
                    "email": email,
                    "to_add": sorted(to_add),
                    "to_remove": sorted(to_remove),
                })
    return {
        "missing": missing,
        "extra": extra,
        "description_mismatch": description_mismatch,
        "member_drift": member_drift,
        "desired_map": desired_map,
    }


# ---------- Remediation ----------

def apply_ou_remediation(service, drift, dry_run=False):
    changes = 0
    for path in drift["missing"]:
        spec = drift["desired_map"][path]
        if dry_run:
            print(f"  [DRY RUN] Would create OU: {path}")
            changes += 1
            continue
        body = {
            "name": spec["name"],
            "description": spec.get("description", ""),
            "parentOrgUnitPath": spec.get("parentOrgUnitPath", "/"),
        }
        try:
            service.orgunits().insert(customerId=CUSTOMER_ID, body=body).execute()
            print(f"  Created OU: {path}")
            changes += 1
        except HttpError as e:
            print(f"  FAILED OU {path}: {e}")
    return changes


def apply_user_remediation(service, drift, dry_run=False):
    changes = 0
    for m in drift["ou_mismatch"]:
        if dry_run:
            print(f"  [DRY RUN] Would move {m['email']}: {m['actual_ou']} -> {m['desired_ou']}")
            changes += 1
            continue
        try:
            service.users().update(
                userKey=m["email"], body={"orgUnitPath": m["desired_ou"]},
            ).execute()
            print(f"  Moved {m['email']}: {m['actual_ou']} -> {m['desired_ou']}")
            changes += 1
        except HttpError as e:
            print(f"  FAILED move {m['email']}: {e}")
    # Note: missing/extra user remediation intentionally omitted —
    # user creation requires passwords, deletion is destructive. Flag only.
    return changes


def apply_group_remediation(service, drift, dry_run=False):
    changes = 0
    for email in drift["missing"]:
        spec = drift["desired_map"][email]
        if dry_run:
            print(f"  [DRY RUN] Would create group: {email}")
            changes += 1
            continue
        try:
            service.groups().insert(body={
                "email": email,
                "name": spec.get("name", email),
                "description": spec.get("description", ""),
            }).execute()
            print(f"  Created group: {email}")
            changes += 1
        except HttpError as e:
            print(f"  FAILED group {email}: {e}")

    for m in drift["member_drift"]:
        group = m["email"]
        for user_email in m["to_add"]:
            if dry_run:
                print(f"  [DRY RUN] {group}: + {user_email}")
                changes += 1
                continue
            try:
                service.members().insert(
                    groupKey=group, body={"email": user_email, "role": "MEMBER"},
                ).execute()
                print(f"  {group}: + {user_email}")
                changes += 1
            except HttpError as e:
                if e.resp.status == 409:
                    continue
                print(f"  FAILED {group} + {user_email}: {e}")
        for user_email in m["to_remove"]:
            if dry_run:
                print(f"  [DRY RUN] {group}: - {user_email}")
                changes += 1
                continue
            try:
                service.members().delete(groupKey=group, memberKey=user_email).execute()
                print(f"  {group}: - {user_email}")
                changes += 1
            except HttpError as e:
                print(f"  FAILED {group} - {user_email}: {e}")
    return changes


# ---------- Output ----------

def print_summary(ou_drift, user_drift, group_drift):
    ou_total = len(ou_drift["missing"]) + len(ou_drift["extra"]) + len(ou_drift["mismatched"])
    user_total = (
        len(user_drift["missing"]) + len(user_drift["extra"])
        + len(user_drift["ou_mismatch"]) + len(user_drift["suspended_mismatch"])
    )
    group_total = (
        len(group_drift["missing"]) + len(group_drift["extra"])
        + len(group_drift["description_mismatch"]) + len(group_drift["member_drift"])
    )

    print(f"\n{'=' * 60}")
    print("GWS RECONCILE — DRIFT SUMMARY")
    print(f"{'=' * 60}")
    print(f"  OU drift:     {ou_total}")
    print(f"    missing:     {len(ou_drift['missing'])}")
    print(f"    extra:       {len(ou_drift['extra'])}")
    print(f"    mismatched:  {len(ou_drift['mismatched'])}")
    print(f"  User drift:   {user_total}")
    print(f"    missing:           {len(user_drift['missing'])}")
    print(f"    extra:             {len(user_drift['extra'])}")
    print(f"    OU-placement:      {len(user_drift['ou_mismatch'])}")
    print(f"    suspended flag:    {len(user_drift['suspended_mismatch'])}")
    print(f"  Group drift:  {group_total}")
    print(f"    missing:           {len(group_drift['missing'])}")
    print(f"    extra:             {len(group_drift['extra'])}")
    print(f"    description:       {len(group_drift['description_mismatch'])}")
    print(f"    member drift:      {len(group_drift['member_drift'])}")
    print(f"  TOTAL drift:  {ou_total + user_total + group_total}")
    print(f"{'=' * 60}")

    for label, drift_list in (
        ("Missing OUs", ou_drift["missing"]),
        ("Extra OUs", ou_drift["extra"]),
        ("Missing users", user_drift["missing"]),
        ("Extra users", user_drift["extra"]),
        ("Missing groups", group_drift["missing"]),
        ("Extra groups", group_drift["extra"]),
    ):
        if drift_list:
            print(f"\n{label}:")
            for item in drift_list:
                print(f"  - {item}")

    if user_drift["ou_mismatch"]:
        print("\nUsers in wrong OU:")
        for m in user_drift["ou_mismatch"]:
            print(f"  - {m['email']}: {m['actual_ou']} -> {m['desired_ou']}")

    if group_drift["member_drift"]:
        print("\nGroup membership drift:")
        for m in group_drift["member_drift"]:
            extras = ", ".join([f"+{e}" for e in m["to_add"]] + [f"-{e}" for e in m["to_remove"]])
            print(f"  - {m['email']}: {extras}")


def generate_report(ou_drift, user_drift, group_drift, desired_meta):
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# GWS Config Reconcile Report",
        f"\n**Generated:** {timestamp}",
        f"**Desired-state exported:** {desired_meta.get('exportedAt', 'unknown')}",
        f"**Domain:** {desired_meta.get('domain', GWS_DOMAIN)}",
        "",
        "## Drift Summary",
        "",
        "| Category | Missing | Extra | Mismatch | Member Drift |",
        "|----------|---------|-------|----------|--------------|",
        f"| OUs | {len(ou_drift['missing'])} | {len(ou_drift['extra'])} | {len(ou_drift['mismatched'])} | — |",
        f"| Users | {len(user_drift['missing'])} | {len(user_drift['extra'])} | {len(user_drift['ou_mismatch'])} | — |",
        f"| Groups | {len(group_drift['missing'])} | {len(group_drift['extra'])} | {len(group_drift['description_mismatch'])} | {len(group_drift['member_drift'])} |",
        "",
    ]

    def section(title, rows):
        if not rows:
            return
        lines.append(f"## {title}\n")
        for r in rows:
            lines.append(f"- {r}")
        lines.append("")

    section("Missing OUs", ou_drift["missing"])
    section("Extra OUs (present in tenant, absent from desired state)", ou_drift["extra"])
    section("Missing users", user_drift["missing"])
    section("Extra users", user_drift["extra"])
    section("Missing groups", group_drift["missing"])
    section("Extra groups", group_drift["extra"])

    if user_drift["ou_mismatch"]:
        lines.append("## Users in Wrong OU\n")
        lines.append("| Email | Desired OU | Actual OU |")
        lines.append("|-------|------------|-----------|")
        for m in user_drift["ou_mismatch"]:
            lines.append(f"| {m['email']} | {m['desired_ou']} | {m['actual_ou']} |")
        lines.append("")

    if group_drift["member_drift"]:
        lines.append("## Group Membership Drift\n")
        for m in group_drift["member_drift"]:
            lines.append(f"### {m['email']}")
            if m["to_add"]:
                lines.append("- **Add:**")
                for e in m["to_add"]:
                    lines.append(f"  - `{e}`")
            if m["to_remove"]:
                lines.append("- **Remove:**")
                for e in m["to_remove"]:
                    lines.append(f"  - `{e}`")
            lines.append("")

    total = (
        len(ou_drift["missing"]) + len(ou_drift["extra"]) + len(ou_drift["mismatched"])
        + len(user_drift["missing"]) + len(user_drift["extra"])
        + len(user_drift["ou_mismatch"]) + len(user_drift["suspended_mismatch"])
        + len(group_drift["missing"]) + len(group_drift["extra"])
        + len(group_drift["description_mismatch"]) + len(group_drift["member_drift"])
    )
    if total == 0:
        lines.append("**No drift detected** — live tenant matches desired state.\n")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/gws/reconcile_config.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Reconcile GWS tenant against desired-state.json")
    parser.add_argument(
        "--admin-email",
        default=os.getenv("GWS_ADMIN_EMAIL"),
        help="Admin email to impersonate",
    )
    parser.add_argument("--in", dest="infile", default=str(DEFAULT_IN), help="Desired-state JSON path")
    parser.add_argument("--apply", action="store_true", help="Remediate drift (destructive)")
    parser.add_argument("--dry-run", action="store_true", help="With --apply, preview without writing")
    parser.add_argument("--report", action="store_true", help="Write markdown drift report")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    desired_path = Path(args.infile)
    desired = load_desired(desired_path)

    mode = "apply" if args.apply else "audit"
    print(f"GWS Config Reconcile — mode: {mode}")
    print(f"Admin: {args.admin_email}")
    print(f"Desired state: {desired_path}")
    print(f"  Exported at: {desired.get('exportedAt')}")
    if args.apply and args.dry_run:
        print("*** DRY RUN — no changes will be made ***")
    print()

    service = get_service(args.admin_email)
    print("Connected to Admin SDK Directory API")

    print("Fetching live tenant state...")
    live_ous = fetch_live_ous(service)
    live_users = fetch_live_users(service)
    live_groups = fetch_live_groups(service)
    print(f"  Live: {len(live_ous)} OUs, {len(live_users)} users, {len(live_groups)} groups")

    print("Computing drift...")
    ou_drift = diff_ous(desired.get("ous", []), live_ous)
    user_drift = diff_users(desired.get("users", []), live_users)
    group_drift = diff_groups(desired.get("groups", []), live_groups)

    print_summary(ou_drift, user_drift, group_drift)

    if args.apply:
        print("\nApplying remediation...")
        ou_changes = apply_ou_remediation(service, ou_drift, args.dry_run)
        user_changes = apply_user_remediation(service, user_drift, args.dry_run)
        group_changes = apply_group_remediation(service, group_drift, args.dry_run)
        print(f"\nRemediation: {ou_changes + user_changes + group_changes} changes "
              f"({ou_changes} OU, {user_changes} user, {group_changes} group)")

    if args.report:
        report = generate_report(ou_drift, user_drift, group_drift, desired)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"reconcile-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
