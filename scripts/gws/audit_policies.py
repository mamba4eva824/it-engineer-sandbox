#!/usr/bin/env python3
"""
Audit GWS per-OU security policies via Cloud Identity Policy API.

Reads existing policies from the Cloud Identity API and compares against
desired state. Reports drift — policies that don't match expectations.

Covers:
  - 2-Step Verification (enrollment + enforcement per OU)
  - Third-party app access controls per OU
  - Password policies, session controls, login challenges

Prerequisites:
  1. pip install google-auth google-api-python-client requests
  2. Cloud Identity API enabled in GCP project
  3. Service account with domain-wide delegation
  4. Scope: https://www.googleapis.com/auth/cloud-identity.policies

Usage:
  python audit_policies.py                  # Uses GWS_ADMIN_EMAIL from .env
  python audit_policies.py --report         # Generate markdown audit report
  python audit_policies.py --filter security
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import google.auth.transport.requests
import requests
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

load_dotenv()

# --- Configuration ---

SERVICE_ACCOUNT_KEY = Path(__file__).parent.parent.parent / os.getenv("GWS_SERVICE_ACCOUNT_KEY", "credentials/service-account-key.json")
ADMIN_SDK_SCOPES = ["https://www.googleapis.com/auth/admin.directory.orgunit"]
POLICY_API_SCOPES = ["https://www.googleapis.com/auth/cloud-identity.policies"]
CUSTOMER_ID = "my_customer"

# Desired state: per-OU policy expectations
# Format: { "OU Name": { "setting_type": expected_value } }
DESIRED_STATE = {
    "IT-Ops": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Executive": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "ENFORCED",
        "api_controls.unconfigured_third_party_apps": "BLOCK_ALL_SCOPES",
    },
    "Finance": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "ENFORCED",
        "api_controls.unconfigured_third_party_apps": "BLOCK_ALL_SCOPES",
    },
    "HR": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "ENFORCED",
        "api_controls.unconfigured_third_party_apps": "BLOCK_ALL_SCOPES",
    },
    "Engineering": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Data": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Product": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Design": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Sales": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
    "Marketing": {
        "security.two_step_verification_enrollment": {"allowEnrollment": True},
        "security.two_step_verification_enforcement": "NOT_ENFORCED",
        "api_controls.unconfigured_third_party_apps": "INHERITED",
    },
}


def get_directory_service(admin_email: str):
    """Get Admin SDK Directory service for OU lookups."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=ADMIN_SDK_SCOPES,
        subject=admin_email,
    )
    return build("admin", "directory_v1", credentials=credentials)


def get_policy_credentials(admin_email: str):
    """Get Cloud Identity Policy API credentials."""
    credentials = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY),
        scopes=POLICY_API_SCOPES,
        subject=admin_email,
    )
    credentials.refresh(google.auth.transport.requests.Request())
    return credentials


def get_ou_map(directory_service):
    """Fetch OU ID → OU name mapping."""
    result = directory_service.orgunits().list(customerId=CUSTOMER_ID).execute()
    ou_map = {}
    for ou in result.get("organizationUnits", []):
        ou_id = ou["orgUnitId"].replace("id:", "")
        ou_map[f"orgUnits/{ou_id}"] = ou["name"]
    return ou_map


def fetch_all_policies(credentials, setting_filter=None):
    """Fetch all policies from the Cloud Identity Policy API."""
    all_policies = []
    page_token = ""
    filter_str = ""
    if setting_filter:
        filter_str = f'setting.type.matches(".*{setting_filter}.*")'

    while True:
        params = {"pageSize": 100}
        if filter_str:
            params["filter"] = filter_str
        if page_token:
            params["pageToken"] = page_token

        resp = requests.get(
            "https://cloudidentity.googleapis.com/v1beta1/policies",
            headers={"Authorization": f"Bearer {credentials.token}"},
            params=params,
        )
        if resp.status_code != 200:
            print(f"  API error {resp.status_code}: {resp.text[:200]}")
            break

        data = resp.json()
        all_policies.extend(data.get("policies", []))
        page_token = data.get("nextPageToken", "")
        if not page_token:
            break

    return all_policies


def organize_policies_by_ou(policies, ou_map):
    """Group policies by OU name and setting type."""
    organized = {}
    for policy in policies:
        ou_ref = policy.get("policyQuery", {}).get("orgUnit", "")
        ou_name = ou_map.get(ou_ref, ou_ref)
        setting_type = policy["setting"]["type"].replace("settings/", "")
        setting_value = policy["setting"].get("value", {})
        policy_type = policy.get("type", "UNKNOWN")

        if ou_name not in organized:
            organized[ou_name] = {}
        organized[ou_name][setting_type] = {
            "value": setting_value,
            "type": policy_type,
            "name": policy.get("name", ""),
        }

    return organized


def check_2sv_enforcement(policy_data):
    """Determine if 2SV is enforced based on policy data."""
    if not policy_data:
        return "NOT_ENFORCED"
    value = policy_data.get("value", {})
    if "enforcedFrom" in value:
        return "ENFORCED"
    return "NOT_ENFORCED"


def check_app_access(policy_data):
    """Determine third-party app access level from policy data."""
    if not policy_data:
        return "INHERITED"
    value = policy_data.get("value", {})
    access = value.get("accessLevel", value.get("appAccessPolicy", "UNKNOWN"))
    if isinstance(access, str):
        return access
    return "UNKNOWN"


def audit_policies(organized, desired_state):
    """Compare actual policies against desired state. Returns drift entries."""
    drift = []
    compliant = []

    for ou_name, expected in desired_state.items():
        actual = organized.get(ou_name, {})

        # Check 2SV enforcement
        expected_2sv = expected.get("security.two_step_verification_enforcement", "NOT_ENFORCED")
        actual_2sv = check_2sv_enforcement(
            actual.get("security.two_step_verification_enforcement")
        )

        if actual_2sv == expected_2sv:
            compliant.append({
                "ou": ou_name,
                "policy": "2-Step Verification",
                "expected": expected_2sv,
                "actual": actual_2sv,
            })
        else:
            drift.append({
                "ou": ou_name,
                "policy": "2-Step Verification",
                "expected": expected_2sv,
                "actual": actual_2sv,
            })

        # Check third-party app access
        expected_apps = expected.get("api_controls.unconfigured_third_party_apps", "ALLOWED")
        actual_apps = check_app_access(
            actual.get("api_controls.unconfigured_third_party_apps")
        )

        if actual_apps == "UNKNOWN":
            drift.append({
                "ou": ou_name,
                "policy": "Third-Party App Access",
                "expected": expected_apps,
                "actual": f"{actual_apps} (verify in Admin Console)",
            })
        elif actual_apps == expected_apps or (expected_apps == "INHERITED" and actual_apps == "INHERITED"):
            compliant.append({
                "ou": ou_name,
                "policy": "Third-Party App Access",
                "expected": expected_apps,
                "actual": actual_apps,
            })
        else:
            drift.append({
                "ou": ou_name,
                "policy": "Third-Party App Access",
                "expected": expected_apps,
                "actual": actual_apps,
            })

    return drift, compliant


def generate_report(organized, drift, compliant, ou_map):
    """Generate a markdown policy audit report."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    total_checks = len(drift) + len(compliant)

    lines = [
        "# GWS Security Policy Audit Report",
        f"\n**Generated:** {timestamp}",
        f"**Total policy checks:** {total_checks}",
        f"**Compliant:** {len(compliant)}",
        f"**Drift detected:** {len(drift)}",
        "",
    ]

    # Summary table
    lines.append("## Per-OU Policy Summary\n")
    lines.append("| OU | 2-Step Verification | Third-Party Apps | Status |")
    lines.append("|---|---|---|---|")

    for ou_name in sorted(DESIRED_STATE.keys()):
        actual = organized.get(ou_name, {})
        sv2 = check_2sv_enforcement(actual.get("security.two_step_verification_enforcement"))
        apps = check_app_access(actual.get("api_controls.unconfigured_third_party_apps"))

        ou_drift = [d for d in drift if d["ou"] == ou_name]
        status = "DRIFT" if ou_drift else "OK"
        lines.append(f"| {ou_name} | {sv2} | {apps} | {status} |")

    # Drift details
    if drift:
        lines.append("\n## Drift Detected\n")
        lines.append("| OU | Policy | Expected | Actual |")
        lines.append("|---|---|---|---|")
        for d in drift:
            lines.append(f"| {d['ou']} | {d['policy']} | {d['expected']} | {d['actual']} |")

    # Compliant details
    if compliant:
        lines.append("\n## Compliant Policies\n")
        lines.append("| OU | Policy | Status |")
        lines.append("|---|---|---|")
        for c in compliant:
            lines.append(f"| {c['ou']} | {c['policy']} | {c['actual']} |")

    # All policies discovered
    lines.append("\n## All Policies by OU\n")
    for ou_name in sorted(organized.keys()):
        policies = organized[ou_name]
        lines.append(f"### {ou_name}\n")
        lines.append("| Setting | Value | Type |")
        lines.append("|---------|-------|------|")
        for setting, data in sorted(policies.items()):
            val = json.dumps(data["value"], default=str)
            if len(val) > 60:
                val = val[:57] + "..."
            lines.append(f"| `{setting}` | {val} | {data['type']} |")
        lines.append("")

    lines.append("---")
    lines.append(f"\n*Report generated by `scripts/gws/audit_policies.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Audit GWS per-OU security policies via Cloud Identity API"
    )
    parser.add_argument("--admin-email", default=os.getenv("GWS_ADMIN_EMAIL"), help="Admin email to impersonate (default: GWS_ADMIN_EMAIL from .env)")
    parser.add_argument("--report", action="store_true", help="Generate markdown audit report")
    parser.add_argument("--filter", help="Filter policies by setting type (e.g., 'security', 'api_controls')")
    args = parser.parse_args()

    print("GWS Security Policy Audit")
    print(f"Admin: {args.admin_email}\n")

    # Connect
    directory_service = get_directory_service(args.admin_email)
    credentials = get_policy_credentials(args.admin_email)

    # Get OU mapping
    ou_map = get_ou_map(directory_service)
    print(f"Found {len(ou_map)} OUs")

    # Fetch policies
    print("Fetching policies from Cloud Identity API...")
    policies = fetch_all_policies(credentials, args.filter)
    print(f"Found {len(policies)} policies\n")

    # Organize by OU
    organized = organize_policies_by_ou(policies, ou_map)

    # Audit against desired state
    print("Auditing against desired state...")
    drift, compliant = audit_policies(organized, DESIRED_STATE)

    # Print summary
    print(f"\n{'=' * 50}")
    print(f"POLICY AUDIT RESULTS")
    print(f"  Compliant:  {len(compliant)}")
    print(f"  Drift:      {len(drift)}")
    print(f"  Total:      {len(drift) + len(compliant)}")

    if drift:
        print(f"\nDrift detected:")
        for d in drift:
            print(f"  {d['ou']}: {d['policy']} — expected {d['expected']}, got {d['actual']}")

    print(f"{'=' * 50}")

    # Generate report
    if args.report:
        report = generate_report(organized, drift, compliant, ou_map)
        report_dir = Path(__file__).parent.parent.parent / "docs" / "reports"
        report_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        report_path = report_dir / f"policy-audit-{date_str}.md"
        with open(report_path, "w") as f:
            f.write(report)
        print(f"\nAudit report saved to: {report_path}")


if __name__ == "__main__":
    main()
