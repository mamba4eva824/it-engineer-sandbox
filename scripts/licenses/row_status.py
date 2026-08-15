"""Overall `status` for ohmgym-license-reclaim-logs.

Scanner persist and broker/CLI reclaim rollup share this so a row with no
scan-`active` seats is never stored as `clean` or `partial`.
"""
from __future__ import annotations

from typing import Any

NO_LICENSES_TO_RECLAIM = "No Licenses to Reclaim"


def enabled_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [a for a in findings if a.get("status") != "skipped"]


def active_app_keys(findings: list[dict[str, Any]]) -> list[str]:
    return [a["app"] for a in enabled_findings(findings) if a.get("status") == "active"]


def _connector_errors(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Scan failures that must not look like 'no licenses' (P2-R13).

    `identity_unresolved` is incomplete identity, not a connector outage — there
    are still no confirmed seats to reclaim.
    """
    return [
        a for a in enabled_findings(findings)
        if a.get("status") == "error" and a.get("error_class") != "identity_unresolved"
    ]


def compute_scan_row_status(findings: list[dict[str, Any]]) -> tuple[str, str | None]:
    enabled = enabled_findings(findings)
    errors = [a for a in enabled if a.get("status") == "error"]
    actives = [a for a in enabled if a.get("status") == "active"]
    connector_errors = _connector_errors(findings)
    if errors and enabled and len(errors) == len(enabled) and connector_errors:
        return "error", "all_connectors_failed"
    if actives:
        return ("partial" if errors else "ticketed"), None
    if connector_errors:
        return "partial", None
    return NO_LICENSES_TO_RECLAIM, None


def compute_reclaim_row_status(
    apps: list[dict[str, Any]],
    reclaim_by_app: dict[str, dict[str, Any]],
) -> str:
    active_apps = [a["app"] for a in (apps or []) if a.get("status") == "active"]
    if not active_apps:
        return NO_LICENSES_TO_RECLAIM
    all_reclaimed = all(
        (reclaim_by_app.get(app) or {}).get("status") == "reclaimed" for app in active_apps
    )
    return "reclaimed" if all_reclaimed else "partial"
