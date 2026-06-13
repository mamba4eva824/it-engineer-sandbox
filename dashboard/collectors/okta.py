"""Okta license usage and JML pipeline collectors."""

from __future__ import annotations

import os

from dashboard.collectors._imports import load_script_module
from dashboard.collectors._utils import (
    LICENSE_STATUSES,
    OFFBOARDING_STATUSES,
    ONBOARDING_STATUSES,
    CollectorError,
    build_license_card,
    days_until,
    normalize_okta_user,
    today_pt,
)

_okta = load_script_module("scripts/okta/_client.py", "dashboard_okta_client")


def _okta_session():
    if not os.getenv("OKTA_ORG_URL"):
        raise CollectorError("OKTA_ORG_URL missing from .env")
    try:
        session, _ = _okta.get_session()
        return session
    except SystemExit as exc:
        raise CollectorError("Okta credentials incomplete in .env") from exc


def _search_users(session, search: str) -> list[dict]:
    return list(
        _okta.paginate(
            session,
            _okta.api_url("/api/v1/users"),
            params={"search": search, "limit": 200},
        )
    )


def _status_search(statuses: tuple[str, ...]) -> str:
    parts = [f'status eq "{s}"' for s in statuses]
    return " or ".join(parts)


def collect_okta_license(purchased: int) -> dict:
    try:
        session = _okta_session()
        search = _status_search(LICENSE_STATUSES)
        users = _search_users(session, search)
        used = len(users)
        return build_license_card("okta", "Okta", used, purchased)
    except CollectorError as exc:
        return build_license_card("okta", "Okta", None, purchased, error=str(exc))
    except Exception as exc:
        return build_license_card("okta", "Okta", None, purchased, error=f"Okta API error: {exc}")


def collect_onboarding_pipeline() -> dict:
    ref = today_pt()
    try:
        session = _okta_session()
        search = _status_search(ONBOARDING_STATUSES)
        raw = _search_users(session, search)
        users = []
        for user in raw:
            normalized = normalize_okta_user(user)
            if normalized["status"] not in ONBOARDING_STATUSES:
                continue
            start_date = normalized.get("startDate")
            if not start_date:
                continue
            days = days_until(start_date, ref)
            badge = None
            if normalized["status"] == "STAGED" and days < 0:
                badge = "missed_activation"
            users.append({**normalized, "daysUntilStart": days, "badge": badge})
        users.sort(key=lambda u: u["startDate"])
        return {"users": users, "count": len(users)}
    except CollectorError as exc:
        return {"users": [], "count": 0, "error": str(exc)}
    except Exception as exc:
        return {"users": [], "count": 0, "error": f"Okta API error: {exc}"}


def collect_offboarding_pipeline() -> dict:
    ref = today_pt()
    try:
        session = _okta_session()
        search = _status_search(OFFBOARDING_STATUSES)
        raw = _search_users(session, search)
        users = []
        for user in raw:
            normalized = normalize_okta_user(user)
            if normalized["status"] not in OFFBOARDING_STATUSES:
                continue
            end_date = normalized.get("endDate")
            if not end_date:
                continue
            days = days_until(end_date, ref)
            badge = "due_today_or_overdue" if days <= 0 else None
            users.append({**normalized, "daysUntilEnd": days, "badge": badge})
        users.sort(key=lambda u: u["endDate"])
        return {"users": users, "count": len(users)}
    except CollectorError as exc:
        return {"users": [], "count": 0, "error": str(exc)}
    except Exception as exc:
        return {"users": [], "count": 0, "error": f"Okta API error: {exc}"}


def okta_health() -> str:
    try:
        _okta_session()
        return "ok"
    except Exception:
        return "error"
