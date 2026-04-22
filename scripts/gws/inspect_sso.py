#!/usr/bin/env python3
"""Inspect Google Workspace inbound SAML SSO configuration.

Read-only diagnostic. Answers three questions before we try an end-to-end SAML
test with Okta:

  1. What SAML SSO profiles exist, and where do they point?
     (Is the "edited" profile actually pointing at Okta, or did the save miss?)
  2. Which OUs/groups are assigned to which profile?
     (Are the canary OU + your test user's OU both routing through the right profile?)
  3. Are recent SAML logins succeeding or failing, and if failing, why?
     (Audience mismatch / NameID mismatch / user not in company are the usual three.)

Prerequisites (one-time):
  - Service account must have these scopes authorized in Admin Console →
    Security → API Controls → Manage Domain-Wide Delegation:
      https://www.googleapis.com/auth/cloud-identity.inboundsso.readonly
      https://www.googleapis.com/auth/admin.reports.audit.readonly

Usage:
  python scripts/gws/inspect_sso.py
  python scripts/gws/inspect_sso.py --days 30
  python scripts/gws/inspect_sso.py --admin-email chris@ohmgym.com
"""

import argparse
import hashlib
import os
import sys
from datetime import datetime, timedelta, timezone
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
    "https://www.googleapis.com/auth/cloud-identity.inboundsso.readonly",
    "https://www.googleapis.com/auth/admin.reports.audit.readonly",
    "https://www.googleapis.com/auth/admin.directory.orgunit",
]


def build_services(admin_email: str):
    creds = service_account.Credentials.from_service_account_file(
        str(SERVICE_ACCOUNT_KEY), scopes=SCOPES, subject=admin_email,
    )
    return {
        "ci": build("cloudidentity", "v1", credentials=creds),
        "reports": build("admin", "reports_v1", credentials=creds),
        "directory": build("admin", "directory_v1", credentials=creds),
    }


def cert_fingerprint(pem_or_der: str) -> str:
    """SHA-256 fingerprint of a PEM or DER-encoded cert string, colon-separated."""
    body = pem_or_der
    if "BEGIN CERTIFICATE" in body:
        body = "".join(
            line for line in body.splitlines()
            if line and not line.startswith("-----")
        )
    try:
        import base64
        der = base64.b64decode(body)
    except Exception:
        return "(unparseable)"
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


def guess_idp(sso_url: str) -> str:
    url = (sso_url or "").lower()
    if "okta.com" in url:
        return "Okta"
    if "auth0.com" in url:
        return "Auth0"
    return "other"


# ---------------- SAML profile inspection ----------------

def list_sso_profiles(ci):
    profiles = []
    page_token = None
    while True:
        req = ci.inboundSamlSsoProfiles().list(
            pageSize=100, pageToken=page_token,
        )
        resp = req.execute()
        profiles.extend(resp.get("inboundSamlSsoProfiles", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return profiles


def print_profiles(profiles):
    print(f"\n=== Inbound SAML SSO Profiles ({len(profiles)}) ===")
    if not profiles:
        print("  (none — tenant has no SAML SSO profiles configured)")
        return

    for p in profiles:
        idp_cfg = p.get("idpConfig", {}) or {}
        sp_cfg = p.get("spConfig", {}) or {}
        sso_url = idp_cfg.get("singleSignOnServiceUri", "")
        print(f"\n  Name:          {p.get('displayName', '(unnamed)')}")
        print(f"  Resource ID:   {p.get('name', '?').split('/')[-1]}")
        print(f"  IdP match:     {guess_idp(sso_url)}")
        print(f"  IdP entity:    {idp_cfg.get('entityId', '(missing)')}")
        print(f"  SSO URL:       {sso_url or '(missing)'}")
        print(f"  Logout URL:    {idp_cfg.get('logoutRedirectUri', '(none)')}")
        print(f"  SP entity:     {sp_cfg.get('entityId', '(missing)')}")
        print(f"  SP ACS URL:    {sp_cfg.get('assertionConsumerServiceUri', '(missing)')}")

        # Signing certs are under a sibling collection, fetch separately
        # (the profile object itself just references them).
        certs = p.get("idpConfig", {}).get("signingCertificates") or []
        for c in certs:
            fp = cert_fingerprint(c.get("pemData", ""))
            print(f"  Cert fingerprint (SHA-256): {fp[:47]}...")


# ---------------- SSO assignments ----------------

def list_sso_assignments(ci):
    assignments = []
    # Cloud Identity lists assignments under customer
    parent = f"customers/{CUSTOMER_ID}"
    # The API expects the numeric customer id; if GWS_CUSTOMER_ID is "my_customer",
    # fall back to fetching it via Directory API.
    page_token = None
    customer_ref = "customers/my_customer" if CUSTOMER_ID == "my_customer" else f"customers/{CUSTOMER_ID}"
    while True:
        req = ci.inboundSsoAssignments().list(
            filter=f'customer=="{customer_ref}"',
            pageSize=100,
            pageToken=page_token,
        )
        resp = req.execute()
        assignments.extend(resp.get("inboundSsoAssignments", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return assignments


def resolve_target_name(directory, target):
    """Best-effort label for an assignment target: OU path or group email."""
    if not target:
        return "(unknown)"
    if target.startswith("orgUnits/"):
        ou_id = target.split("/")[-1]
        try:
            ou = directory.orgunits().get(
                customerId=CUSTOMER_ID, orgUnitPath=f"id:{ou_id}",
            ).execute()
            return f"OU {ou.get('orgUnitPath', '?')}"
        except HttpError:
            return f"OU id:{ou_id}"
    if target.startswith("groups/"):
        return f"Group {target.split('/')[-1]}"
    return target


def print_assignments(assignments, profiles, directory):
    profile_name = {p["name"]: p.get("displayName", p["name"]) for p in profiles}
    print(f"\n=== SSO Profile Assignments ({len(assignments)}) ===")
    if not assignments:
        print("  (none — no OUs or groups are assigned to any SAML profile)")
        return

    for a in assignments:
        target = a.get("targetOrgUnit") or a.get("targetGroup") or "(root)"
        target_label = resolve_target_name(directory, target)
        sso_mode = a.get("ssoMode", "?")
        profile_ref = a.get("samlSsoInfo", {}).get("inboundSamlSsoProfile", "")
        profile_label = profile_name.get(profile_ref, profile_ref.split("/")[-1] or "(none)")
        print(f"  {target_label:35s}  →  {sso_mode:20s}  {profile_label}")


# ---------------- Login events ----------------

def fetch_saml_events(reports, days: int):
    start = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    events = []
    page_token = None
    while True:
        try:
            resp = reports.activities().list(
                userKey="all", applicationName="saml",
                startTime=start, maxResults=1000, pageToken=page_token,
            ).execute()
        except HttpError as e:
            if e.resp.status == 403:
                print(f"  (Reports API scope not authorized: {e.error_details or e})")
                return []
            raise
        events.extend(resp.get("items", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return events


def summarize_events(events, days: int):
    print(f"\n=== SAML Events (last {days} days, {len(events)} total) ===")
    if not events:
        print("  (none — no SAML logins attempted in window)")
        return

    success = failure = 0
    failure_reasons: dict[str, int] = {}
    recent_users: set[str] = set()
    for e in events:
        actor_email = (e.get("actor", {}) or {}).get("email", "")
        recent_users.add(actor_email)
        for ev in e.get("events", []):
            name = ev.get("name", "")
            if name == "login_success":
                success += 1
            elif name == "login_failure":
                failure += 1
                params = {p.get("name"): p.get("value") for p in ev.get("parameters", [])}
                reason = params.get("failure_type") or params.get("saml_status_code") or "unknown"
                failure_reasons[reason] = failure_reasons.get(reason, 0) + 1

    print(f"  login_success: {success}")
    print(f"  login_failure: {failure}")
    if failure_reasons:
        for reason, count in sorted(failure_reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count}")
    print(f"  Distinct actors: {len(recent_users)}")
    if recent_users and len(recent_users) <= 10:
        for u in sorted(recent_users):
            if u:
                print(f"    {u}")


# ---------------- Main ----------------

def main():
    parser = argparse.ArgumentParser(description="Inspect GWS SAML SSO config + recent events")
    parser.add_argument("--admin-email", default=os.getenv("GWS_ADMIN_EMAIL"),
                        help="Admin email to impersonate via DWD")
    parser.add_argument("--days", type=int, default=7,
                        help="Days of SAML events to summarize (default: 7)")
    args = parser.parse_args()

    if not args.admin_email:
        print("ERROR: --admin-email or GWS_ADMIN_EMAIL required")
        sys.exit(1)

    print(f"GWS SAML SSO Inspection")
    print(f"Admin:       {args.admin_email}")
    print(f"Customer:    {CUSTOMER_ID}")
    print(f"Domain:      {GWS_DOMAIN}")

    services = build_services(args.admin_email)

    try:
        profiles = list_sso_profiles(services["ci"])
    except HttpError as e:
        if e.resp.status == 403:
            print(f"\nERROR: Cloud Identity scope not authorized. Add this scope in")
            print(f"Admin Console → Security → API Controls → Domain-Wide Delegation:")
            print(f"  https://www.googleapis.com/auth/cloud-identity.inboundsso.readonly")
            sys.exit(1)
        raise

    print_profiles(profiles)
    try:
        assignments = list_sso_assignments(services["ci"])
    except HttpError as e:
        print(f"\n(Could not list assignments: {e})")
        assignments = []
    print_assignments(assignments, profiles, services["directory"])

    events = fetch_saml_events(services["reports"], args.days)
    summarize_events(events, args.days)


if __name__ == "__main__":
    main()
