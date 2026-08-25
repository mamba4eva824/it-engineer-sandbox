"""ReclaimPlan schema and hard-deny policy intersect for the orchestrator.

The model may only classify apps in the candidate set. This module strips
anything the LLM invents and applies holds the model cannot override.
`auto_reclaim` on an allowlist entry is a planner *hint* only — never a
silent bypass of the planner or of these denials.
"""
from __future__ import annotations

from typing import Any, Iterable, TypedDict

FIXTURE_ISSUE_KEY = "SUP-2"
HOLD_KEYWORDS = (
    "do not reclaim",
    "legal hold",
    "litigation",
    "sample",
    "fixture",
)
PLAN_ACTIONS = ("reclaim", "skip", "hold")


class PlanDecision(TypedDict):
    app: str
    action: str
    reason: str


class ReclaimPlan(TypedDict):
    issue_key: str
    user_email: str
    decisions: list[PlanDecision]
    confidence: float


def parse_app_list(raw: Any) -> list[str]:
    """Ticket customfield_10141 is a comma-separated string of app keys."""
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        values = str(raw).replace(";", ",").split(",")
    out: list[str] = []
    seen: set[str] = set()
    for item in values:
        key = str(item).strip().lower()
        if not key or key in ("none", "n/a", "-"):
            continue
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def notes_text(raw: Any) -> str:
    if raw is None:
        return ""
    return str(raw).strip()


def hold_notes_blocked(notes: str) -> bool:
    lowered = (notes or "").lower()
    return any(keyword in lowered for keyword in HOLD_KEYWORDS)


def enabled_allowlist(apps_config: dict[str, Any]) -> dict[str, Any]:
    return {
        key: spec
        for key, spec in (apps_config or {}).items()
        if isinstance(spec, dict) and spec.get("enabled")
    }


def scan_active_apps(findings: Iterable[dict[str, Any]]) -> list[str]:
    active: list[str] = []
    for finding in findings or []:
        app = str(finding.get("app") or "").strip()
        if app and finding.get("status") == "active":
            active.append(app)
    return active


def candidate_apps(
    *,
    apps_config: dict[str, Any],
    findings: list[dict[str, Any]],
    ticket_apps: list[str],
) -> list[str]:
    """Enabled allowlist ∩ scan-active ∩ on the ticket.

    `error` / `not_assigned` / `identity_unresolved` never enter the set the
    model is allowed to reclaim.
    """
    enabled = enabled_allowlist(apps_config)
    active = set(scan_active_apps(findings))
    ticket = set(ticket_apps)
    return [app for app in enabled if app in active and app in ticket]


def empty_plan(issue_key: str, user_email: str, *, reason: str) -> ReclaimPlan:
    return {
        "issue_key": issue_key,
        "user_email": user_email,
        "decisions": [],
        "confidence": 0.0,
    }


def normalize_plan(raw: Any, *, issue_key: str, user_email: str) -> ReclaimPlan:
    if not isinstance(raw, dict):
        return empty_plan(issue_key, user_email, reason="invalid_plan")
    decisions: list[PlanDecision] = []
    for item in raw.get("decisions") or []:
        if not isinstance(item, dict):
            continue
        app = str(item.get("app") or "").strip().lower()
        action = str(item.get("action") or "").strip().lower()
        reason = str(item.get("reason") or "").strip()
        if not app or action not in PLAN_ACTIONS:
            continue
        decisions.append({"app": app, "action": action, "reason": reason or action})
    try:
        confidence = float(raw.get("confidence") or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    return {
        "issue_key": str(raw.get("issue_key") or issue_key).strip() or issue_key,
        "user_email": str(raw.get("user_email") or user_email).strip() or user_email,
        "decisions": decisions,
        "confidence": max(0.0, min(1.0, confidence)),
    }


def intersect_plan(
    plan: ReclaimPlan,
    *,
    issue_key: str,
    user_email: str,
    candidates: list[str],
    ticket_apps: list[str],
    notes: str,
) -> ReclaimPlan:
    """Hard denials the model cannot override. Extra apps/emails are dropped."""
    candidate_set = set(candidates)
    ticket_set = set(ticket_apps)
    forced_hold = (
        issue_key == FIXTURE_ISSUE_KEY
        or hold_notes_blocked(notes)
        or plan.get("issue_key") != issue_key
        or (plan.get("user_email") or "").lower() != (user_email or "").lower()
    )

    by_app: dict[str, PlanDecision] = {}
    for decision in plan.get("decisions") or []:
        app = decision["app"]
        if app not in candidate_set or app not in ticket_set:
            continue
        action = "hold" if forced_hold else decision["action"]
        reason = decision["reason"]
        if forced_hold and issue_key == FIXTURE_ISSUE_KEY:
            reason = "fixture ticket; orchestrator refuses reclaim"
        elif forced_hold and hold_notes_blocked(notes):
            reason = "hold notes match a hard-deny keyword"
        elif forced_hold:
            reason = "plan identity did not match the ticket"
        by_app[app] = {"app": app, "action": action, "reason": reason}

    if forced_hold:
        for app in candidates:
            if app not in by_app:
                by_app[app] = {
                    "app": app,
                    "action": "hold",
                    "reason": (
                        "fixture ticket; orchestrator refuses reclaim"
                        if issue_key == FIXTURE_ISSUE_KEY
                        else "hold notes match a hard-deny keyword"
                        if hold_notes_blocked(notes)
                        else "plan identity did not match the ticket"
                    ),
                }

    # Every candidate must appear so skip/hold is explicit for the comment.
    for app in candidates:
        if app not in by_app:
            by_app[app] = {
                "app": app,
                "action": "hold",
                "reason": "model omitted app; default hold",
            }

    return {
        "issue_key": issue_key,
        "user_email": user_email,
        "decisions": [by_app[app] for app in candidates if app in by_app],
        "confidence": 0.0 if forced_hold else plan.get("confidence") or 0.0,
    }


def reclaim_apps(plan: ReclaimPlan) -> list[str]:
    return [d["app"] for d in plan.get("decisions") or [] if d.get("action") == "reclaim"]


def hold_apps(plan: ReclaimPlan) -> list[str]:
    return [d["app"] for d in plan.get("decisions") or [] if d.get("action") == "hold"]
