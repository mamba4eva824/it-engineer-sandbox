"""Shared helpers for building dashboard API responses."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

_PT = ZoneInfo("America/Los_Angeles")

LICENSE_STATUSES = ("ACTIVE", "PROVISIONED", "STAGED")
ONBOARDING_STATUSES = ("STAGED", "PROVISIONED")
OFFBOARDING_STATUSES = ("ACTIVE", "PROVISIONED")


class CollectorError(Exception):
    """Raised when a collector cannot reach its upstream API."""


def today_pt() -> date:
    return datetime.now(_PT).date()


def days_until(iso_date: str, ref: date | None = None) -> int:
    ref = ref or today_pt()
    target = date.fromisoformat(iso_date)
    return (target - ref).days


def build_license_card(
    service_id: str,
    label: str,
    used: int | None,
    purchased: int | None,
    *,
    detail: str | None = None,
    error: str | None = None,
) -> dict:
    if error:
        return {
            "id": service_id,
            "label": label,
            "used": used,
            "purchased": purchased,
            "available": None,
            "utilizationPct": None,
            "status": "error",
            "detail": error,
        }

    available = (purchased - used) if purchased is not None and used is not None else None
    utilization_pct = (
        round(used / purchased * 100, 1) if purchased and used is not None and purchased > 0 else None
    )

    if purchased is not None and used is not None and used >= purchased:
        status = "critical"
    elif utilization_pct is not None and utilization_pct >= 90:
        status = "warning"
    else:
        status = "ok"

    return {
        "id": service_id,
        "label": label,
        "used": used,
        "purchased": purchased,
        "available": available,
        "utilizationPct": utilization_pct,
        "status": status,
        "detail": detail,
    }


def normalize_okta_user(user: dict) -> dict:
    profile = user.get("profile") or {}
    return {
        "id": user.get("id"),
        "name": f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip(),
        "email": profile.get("email") or profile.get("login"),
        "department": profile.get("department"),
        "roleTitle": profile.get("role_title"),
        "status": user.get("status"),
        "startDate": profile.get("startDate"),
        "endDate": profile.get("endDate"),
    }
