"""Load dashboard configuration from config/dashboard/."""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
LICENSE_LIMITS_PATH = REPO_ROOT / "config" / "dashboard" / "license-limits.json"


def load_license_limits() -> dict:
    with LICENSE_LIMITS_PATH.open(encoding="utf-8") as f:
        return json.load(f)
