"""Slack active member license collector."""

from __future__ import annotations

import os

from dashboard.collectors._imports import load_script_module
from dashboard.collectors._utils import CollectorError, build_license_card

_slack = load_script_module("scripts/slack/_client.py", "dashboard_slack_client")


def _count_active_members() -> int:
    team_id = os.getenv("SLACK_TEAM_ID", "").strip().strip('"')
    if not team_id:
        raise CollectorError("SLACK_TEAM_ID missing from .env (required for admin.users.list)")

    try:
        session = _slack.get_session()
    except SystemExit as exc:
        raise CollectorError("Slack credentials incomplete in .env") from exc

    count = 0
    for member in _slack.paginate(
        session,
        "admin.users.list",
        params={"team_id": team_id, "limit": 100},
        items_key="users",
    ):
        if member.get("is_bot") or member.get("deleted"):
            continue
        count += 1
    return count


def collect_slack_license(purchased: int) -> dict:
    try:
        if not os.getenv("SLACK_USER_TOKEN"):
            raise CollectorError("SLACK_USER_TOKEN missing from .env")
        used = _count_active_members()
        return build_license_card("slack", "Slack", used, purchased)
    except CollectorError as exc:
        return build_license_card("slack", "Slack", None, purchased, error=str(exc))
    except _slack.SlackAPIError as exc:
        hint = (
            " Grant admin.users:read on SLACK_USER_TOKEN, or count seats via "
            "scripts/slack/audit_log_query.py as documented in scripts/dashboard/README.md."
        )
        return build_license_card(
            "slack", "Slack", None, purchased, error=f"Slack API error: {exc.error}.{hint}"
        )
    except Exception as exc:
        return build_license_card("slack", "Slack", None, purchased, error=f"Slack API error: {exc}")


def slack_health() -> str:
    try:
        if not os.getenv("SLACK_USER_TOKEN"):
            return "error"
        _slack.get_session()
        return "ok"
    except Exception:
        return "error"
