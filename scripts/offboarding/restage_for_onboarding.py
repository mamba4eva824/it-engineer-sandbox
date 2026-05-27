#!/usr/bin/env python3
"""Prepare leaver-demo users for Phase 2 onboarding workflow replay.

Okta does not allow profile updates on DEPROVISIONED users on this tenant.
Flow per user:
  1. If DEPROVISIONED → activate?sendEmail=false (→ PROVISIONED)
  2. PUT profile.startDate + clear endDate (while PROVISIONED/ACTIVE)
  3. Revoke sessions + deactivate (→ DEPROVISIONED)
  4. invoke_onboarding_workflow.py matches DEPROVISIONED + startDate

Usage:
  python scripts/offboarding/restage_for_onboarding.py --name "Alex Novak" --name "Jordan Kim"
  python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts" / "okta"))
from _client import api_url, get_session  # noqa: E402


def _today_pt() -> str:
    return datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()


def _find_by_name(session, name: str) -> list[dict]:
    parts = name.strip().split(None, 1)
    if len(parts) == 2:
        search = f'profile.firstName eq "{parts[0]}" and profile.lastName eq "{parts[1]}"'
    else:
        search = f'profile.lastName eq "{parts[0]}"'
    resp = session.get(api_url("/api/v1/users"), params={"search": search, "limit": 10}, timeout=15)
    resp.raise_for_status()
    return resp.json() or []


def _to_provisioned(session, uid: str, status: str, login: str, dry_run: bool) -> bool:
    if status in ("PROVISIONED", "ACTIVE", "RECOVERY", "PASSWORD_EXPIRED"):
        return True
    if status == "DEPROVISIONED":
        if dry_run:
            print(f"  [DRY RUN] Would activate {login} (sendEmail=false)")
            return True
        ar = session.post(
            api_url(f"/api/v1/users/{uid}/lifecycle/activate"),
            params={"sendEmail": "false"},
            timeout=30,
        )
        if ar.status_code not in (200, 204):
            print(f"  FAILED activate {login}: HTTP {ar.status_code} {ar.text[:200]}")
            return False
        return True
    print(f"  SKIP {login}: unsupported status={status}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare leaver-demo users for onboarding replay.")
    parser.add_argument("--name", action="append", required=True)
    parser.add_argument("--start-date", default=_today_pt())
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    session, _ = get_session()
    ok = 0
    for name in args.name:
        users = _find_by_name(session, name)
        if not users:
            print(f"WARN: not found: {name}")
            continue
        user = users[0]
        uid = user["id"]
        status = user.get("status")
        login = (user.get("profile") or {}).get("login", uid)
        print(f"Preparing {name} ({login}) status={status}")

        if not _to_provisioned(session, uid, status, login, args.dry_run):
            continue
        if args.dry_run:
            print(f"  [DRY RUN] Would set startDate={args.start_date}, deactivate")
            ok += 1
            continue

        refreshed = session.get(api_url(f"/api/v1/users/{uid}"), timeout=15).json()
        profile = dict(refreshed.get("profile") or {})
        profile["startDate"] = args.start_date
        profile.pop("endDate", None)
        ur = session.put(api_url(f"/api/v1/users/{uid}"), json={"profile": profile}, timeout=15)
        if ur.status_code >= 300:
            print(f"  FAILED profile update: HTTP {ur.status_code} {ur.text[:200]}")
            continue

        session.delete(api_url(f"/api/v1/users/{uid}/sessions"), timeout=10)
        dr = session.post(api_url(f"/api/v1/users/{uid}/lifecycle/deactivate"), timeout=30)
        if dr.status_code not in (200, 204):
            print(f"  FAILED deactivate: HTTP {dr.status_code} {dr.text[:200]}")
            continue

        final = session.get(api_url(f"/api/v1/users/{uid}"), timeout=15).json()
        print(
            f"  Ready: status={final.get('status')} "
            f"startDate={final.get('profile', {}).get('startDate')} "
            f"endDate={final.get('profile', {}).get('endDate')}"
        )
        ok += 1

    if ok:
        print("\nNext: python scripts/onboarding/invoke_onboarding_workflow.py --tail-logs")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
