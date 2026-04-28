#!/usr/bin/env python3
"""
Apply Slack-side SAML overrides on the Okta Slack OIN app.

Precedent: public-docs/04-okta-migration.md §"Issue 3" — Okta's OIN apps hide
ssoAcsUrlOverride / audienceOverride / recipientOverride / destinationOverride
from the admin UI. When an SP has been upgraded to a newer SAML profile model
that doesn't match the OIN template's defaults, these four fields (via the
Management API) are the designated escape hatch.

This script is the Slack analogue of the GWS fix. The stock "Slack" OIN app was
built for per-workspace Slack; Enterprise Grid org-level SAML expects different
Audience/ACS/Destination URIs. Setting the four overrides lets Okta emit an
assertion Slack Grid's validator accepts.

Usage:
  python scripts/okta/apply_slack_saml_overrides.py --dry-run
  python scripts/okta/apply_slack_saml_overrides.py --apply
  python scripts/okta/apply_slack_saml_overrides.py --apply --fallback
  python scripts/okta/apply_slack_saml_overrides.py --clear
"""

import argparse
import json
import sys

from _client import api_url, get_session


APP_ID = "0oa127roo2hy53i5O698"
GRID_ORG_ORIGIN = "https://ohmgym-sandbox.enterprise.slack.com"
ACS_URL = f"{GRID_ORG_ORIGIN}/sso/saml"

# Candidate A — workspace-origin pattern. Audience = full Grid org URL.
CANDIDATE_A = {
    "ssoAcsUrlOverride":   ACS_URL,
    "audienceOverride":    GRID_ORG_ORIGIN,
    "recipientOverride":   ACS_URL,
    "destinationOverride": ACS_URL,
}

# Candidate B — flat slack.com pattern. Audience = https://slack.com.
CANDIDATE_B = {
    "ssoAcsUrlOverride":   ACS_URL,
    "audienceOverride":    "https://slack.com",
    "recipientOverride":   ACS_URL,
    "destinationOverride": ACS_URL,
}

CLEAR = {k: None for k in CANDIDATE_A}


def diff(current: dict, planned: dict) -> str:
    """Pretty-print a before/after diff of the 4 override fields."""
    lines = []
    for k in ("ssoAcsUrlOverride", "audienceOverride", "recipientOverride", "destinationOverride"):
        c = current.get(k)
        p = planned.get(k)
        if c == p:
            lines.append(f"  {k:22s}  (unchanged: {c!r})")
        else:
            lines.append(f"  {k:22s}  {c!r}")
            lines.append(f"  {'':22s}  -> {p!r}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Apply SAML *Override fields on the Okta Slack OIN app.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Preview the override diff; make no API writes.")
    mode.add_argument("--apply", action="store_true", help="PUT the overrides on the Okta app.")
    mode.add_argument("--clear", action="store_true", help="Set all 4 overrides back to null (rollback).")
    parser.add_argument("--fallback", action="store_true",
                        help="Use Candidate B (Audience=https://slack.com) instead of Candidate A.")
    args = parser.parse_args()

    if args.clear:
        planned_overrides = CLEAR
        label = "CLEAR"
    elif args.fallback:
        planned_overrides = CANDIDATE_B
        label = "Candidate B (flat slack.com Audience)"
    else:
        planned_overrides = CANDIDATE_A
        label = "Candidate A (workspace-origin Audience)"

    session, _ = get_session()

    r = session.get(api_url(f"/api/v1/apps/{APP_ID}"), timeout=15)
    r.raise_for_status()
    app = r.json()
    current = app.get("settings", {}).get("signOn", {})

    print(f"Target app: {app.get('label')}  (id={APP_ID}, name={app.get('name')})")
    print(f"Plan:       {label}")
    print()
    print("Override field diff:")
    print(diff(current, planned_overrides))
    print()

    if args.dry_run:
        print("--dry-run: no API writes. Run with --apply to commit.")
        return

    # Mutate the four override fields in-place on the full app object
    app.setdefault("settings", {}).setdefault("signOn", {})
    for k, v in planned_overrides.items():
        app["settings"]["signOn"][k] = v

    r = session.put(api_url(f"/api/v1/apps/{APP_ID}"), json=app, timeout=30)
    if r.status_code != 200:
        print(f"FAIL: HTTP {r.status_code}")
        print(r.text[:500])
        sys.exit(1)

    new_signon = r.json().get("settings", {}).get("signOn", {})
    print("Okta confirmed new signOn block:")
    print(json.dumps({k: new_signon.get(k) for k in planned_overrides.keys()}, indent=2))
    print()
    print("Done. Next: incognito sign-in as samantha.anderson@ohmgym.com and click the Slack tile.")


if __name__ == "__main__":
    main()
