"""Google Workspace license assignment collectors."""

from __future__ import annotations

import os

from dashboard.collectors._imports import load_script_module
from dashboard.collectors._utils import CollectorError, build_license_card

_gws = load_script_module("scripts/gws/_licensing.py", "dashboard_gws_licensing")


def _gws_service():
    admin_email = os.getenv("GWS_ADMIN_EMAIL")
    if not admin_email:
        raise CollectorError("GWS_ADMIN_EMAIL missing from .env")
    return _gws.get_service(admin_email)


def _format_sku_detail(assignments: list[dict]) -> str | None:
    breakdown = _gws.sku_breakdown(assignments)
    if not breakdown:
        return None
    parts = [f"{sku}: {count}" for sku, count in sorted(breakdown.items())]
    return "; ".join(parts)


def collect_gws_product(service_id: str, label: str, product_id: str, purchased: int | None) -> dict:
    try:
        service = _gws_service()
        assignments = _gws.list_all_assignments(service, product_id, _gws.GWS_DOMAIN)
        used = _gws.count_unique_users(assignments)
        detail = _format_sku_detail(assignments)
        return build_license_card(service_id, label, used, purchased, detail=detail)
    except CollectorError as exc:
        return build_license_card(service_id, label, None, purchased, error=str(exc))
    except Exception as exc:
        return build_license_card(service_id, label, None, purchased, error=f"GWS API error: {exc}")


def gws_health() -> str:
    try:
        _gws_service()
        return "ok"
    except Exception:
        return "error"
