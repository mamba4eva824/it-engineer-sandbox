"""Unit tests for SaaS License Dashboard collectors."""

from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest

from dashboard.collectors._utils import (
    build_license_card,
    days_until,
    normalize_okta_user,
)
from dashboard.collectors.okta import collect_onboarding_pipeline, collect_offboarding_pipeline


class TestBuildLicenseCard:
    def test_available_and_utilization(self):
        card = build_license_card("okta", "Okta", 7, 10)
        assert card["available"] == 3
        assert card["utilizationPct"] == 70.0
        assert card["status"] == "ok"

    def test_critical_at_cap(self):
        card = build_license_card("slack", "Slack", 8, 8)
        assert card["available"] == 0
        assert card["status"] == "critical"

    def test_warning_at_ninety_percent(self):
        card = build_license_card("okta", "Okta", 9, 10)
        assert card["status"] == "warning"

    def test_null_purchased_shows_used_only(self):
        card = build_license_card("gws_workspace", "Google Workspace", 1, None)
        assert card["available"] is None
        assert card["utilizationPct"] is None
        assert card["status"] == "ok"

    def test_error_card(self):
        card = build_license_card("slack", "Slack", None, 8, error="token missing")
        assert card["status"] == "error"
        assert card["detail"] == "token missing"


class TestDaysUntil:
    def test_future_date(self):
        assert days_until("2099-01-01", date(2098, 12, 31)) == 1

    def test_past_date(self):
        assert days_until("2020-01-01", date(2020, 1, 10)) == -9


class TestNormalizeOktaUser:
    def test_maps_profile_fields(self):
        user = {
            "id": "u1",
            "status": "STAGED",
            "profile": {
                "firstName": "Priya",
                "lastName": "Patel",
                "email": "priya@ohmgym.com",
                "department": "Data",
                "role_title": "Data Engineer",
                "startDate": "2026-06-15",
            },
        }
        normalized = normalize_okta_user(user)
        assert normalized["name"] == "Priya Patel"
        assert normalized["roleTitle"] == "Data Engineer"
        assert normalized["startDate"] == "2026-06-15"


def _okta_user(status: str, start_date: str | None = None, end_date: str | None = None) -> dict:
    profile = {
        "firstName": "Test",
        "lastName": "User",
        "email": "test@ohmgym.com",
        "department": "Engineering",
        "role_title": "Engineer",
    }
    if start_date:
        profile["startDate"] = start_date
    if end_date:
        profile["endDate"] = end_date
    return {"id": "u-test", "status": status, "profile": profile}


class TestOnboardingPipeline:
    @patch("dashboard.collectors.okta._search_users")
    @patch("dashboard.collectors.okta._okta_session")
    @patch("dashboard.collectors.okta.today_pt", return_value=date(2026, 6, 12))
    def test_filters_and_sorts_by_start_date(self, _today, _session, search):
        search.return_value = [
            _okta_user("STAGED", start_date="2026-06-20"),
            _okta_user("PROVISIONED", start_date="2026-06-15"),
            _okta_user("STAGED"),  # no startDate — excluded
            _okta_user("ACTIVE", start_date="2026-06-10"),  # wrong status — excluded by search mock
        ]
        result = collect_onboarding_pipeline()
        assert result["count"] == 2
        assert result["users"][0]["startDate"] == "2026-06-15"
        assert result["users"][1]["startDate"] == "2026-06-20"

    @patch("dashboard.collectors.okta._search_users")
    @patch("dashboard.collectors.okta._okta_session")
    @patch("dashboard.collectors.okta.today_pt", return_value=date(2026, 6, 12))
    def test_missed_activation_badge(self, _today, _session, search):
        search.return_value = [_okta_user("STAGED", start_date="2026-06-01")]
        result = collect_onboarding_pipeline()
        assert result["users"][0]["badge"] == "missed_activation"
        assert result["users"][0]["daysUntilStart"] < 0


class TestOffboardingPipeline:
    @patch("dashboard.collectors.okta._search_users")
    @patch("dashboard.collectors.okta._okta_session")
    @patch("dashboard.collectors.okta.today_pt", return_value=date(2026, 6, 12))
    def test_filters_and_sorts_by_end_date(self, _today, _session, search):
        search.return_value = [
            _okta_user("ACTIVE", end_date="2026-06-30"),
            _okta_user("PROVISIONED", end_date="2026-06-15"),
            _okta_user("ACTIVE"),  # no endDate — excluded
        ]
        result = collect_offboarding_pipeline()
        assert result["count"] == 2
        assert result["users"][0]["endDate"] == "2026-06-15"

    @patch("dashboard.collectors.okta._search_users")
    @patch("dashboard.collectors.okta._okta_session")
    @patch("dashboard.collectors.okta.today_pt", return_value=date(2026, 6, 12))
    def test_due_today_badge(self, _today, _session, search):
        search.return_value = [_okta_user("ACTIVE", end_date="2026-06-12")]
        result = collect_offboarding_pipeline()
        assert result["users"][0]["badge"] == "due_today_or_overdue"


class TestGwsSkuBreakdown:
    def test_sku_breakdown_counts(self):
        from scripts.gws._licensing import count_unique_users, sku_breakdown

        assignments = [
            {"userId": "a@x.com", "skuName": "Business Starter"},
            {"userId": "b@x.com", "skuName": "Business Starter"},
            {"userId": "a@x.com", "skuName": "Business Starter"},
        ]
        assert count_unique_users(assignments) == 2
        assert sku_breakdown(assignments) == {"Business Starter": 3}
