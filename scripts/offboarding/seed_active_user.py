#!/usr/bin/env python3
"""Prepare an ACTIVE Okta user for the offboarding-workflow smoke test.

Sets profile.endDate on an existing user (does not create users). For new
hire setup use scripts/onboarding/seed_staged_user.py instead.

Typical demo subjects (already activated via onboarding on 2026-05-15):
  Alex Novak, Jordan Kim — use --name or --login after endDate exists in schema.

Usage:
  python scripts/offboarding/seed_active_user.py \\
    --name "Alex Novak" --end-date 2026-05-27

  python scripts/offboarding/seed_active_user.py \\
    --login chris+alex@ohmgym.com --end-date 2026-05-27
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> int:
    # Delegate to set_end_date.py — same folder, same contract.
    cmd = [sys.executable, str(HERE / "set_end_date.py"), *sys.argv[1:]]
    return subprocess.call(cmd)


if __name__ == "__main__":
    raise SystemExit(main())
