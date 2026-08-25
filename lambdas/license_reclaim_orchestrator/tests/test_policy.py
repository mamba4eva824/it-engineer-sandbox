"""Policy intersect unit tests — no AWS, no OpenAI."""
from __future__ import annotations

import json
from pathlib import Path

import policy

APPS = json.loads(
    (Path(__file__).resolve().parents[3] / "config" / "licenses" / "apps.json").read_text()
)


def test_fixture_issue_is_hard_denied():
    plan = policy.normalize_plan(
        {
            "issue_key": "SUP-2",
            "user_email": "leaver@ohmgym.com",
            "confidence": 1,
            "decisions": [{"app": "github", "action": "reclaim", "reason": "go"}],
        },
        issue_key="SUP-2",
        user_email="leaver@ohmgym.com",
    )
    out = policy.intersect_plan(
        plan,
        issue_key="SUP-2",
        user_email="leaver@ohmgym.com",
        candidates=["github"],
        ticket_apps=["github"],
        notes="",
    )
    assert policy.reclaim_apps(out) == []
    assert policy.hold_apps(out) == ["github"]


def test_legal_hold_notes_force_hold():
    plan = policy.normalize_plan(
        {
            "issue_key": "SUP-10",
            "user_email": "leaver@ohmgym.com",
            "confidence": 0.9,
            "decisions": [
                {"app": "github", "action": "reclaim", "reason": "active"},
                {"app": "jira", "action": "reclaim", "reason": "active"},
            ],
        },
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
    )
    out = policy.intersect_plan(
        plan,
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
        candidates=["github", "jira"],
        ticket_apps=["github", "jira"],
        notes="Legal hold — do not reclaim until counsel signs off",
    )
    assert policy.reclaim_apps(out) == []
    assert set(policy.hold_apps(out)) == {"github", "jira"}


def test_linear_error_is_not_a_candidate():
    findings = [
        {"app": "github", "status": "active"},
        {"app": "linear", "status": "error", "error_class": "retryable"},
        {"app": "jira", "status": "active"},
    ]
    candidates = policy.candidate_apps(
        apps_config=APPS,
        findings=findings,
        ticket_apps=["github", "linear", "jira"],
    )
    assert candidates == ["github", "jira"]
    assert "linear" not in candidates


def test_figma_disabled_and_hallucinated_app_stripped():
    findings = [
        {"app": "github", "status": "active"},
        {"app": "jira", "status": "active"},
    ]
    candidates = policy.candidate_apps(
        apps_config=APPS,
        findings=findings,
        ticket_apps=["github", "jira"],
    )
    plan = policy.normalize_plan(
        {
            "issue_key": "SUP-10",
            "user_email": "leaver@ohmgym.com",
            "confidence": 0.4,
            "decisions": [
                {"app": "github", "action": "reclaim", "reason": "ok"},
                {"app": "figma", "action": "reclaim", "reason": "hallucinated"},
                {"app": "jira", "action": "skip", "reason": "already gone"},
            ],
        },
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
    )
    out = policy.intersect_plan(
        plan,
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
        candidates=candidates,
        ticket_apps=["github", "jira"],
        notes="",
    )
    assert "figma" not in [d["app"] for d in out["decisions"]]
    assert policy.reclaim_apps(out) == ["github"]


def test_email_mismatch_forces_hold():
    plan = policy.normalize_plan(
        {
            "issue_key": "SUP-10",
            "user_email": "other@ohmgym.com",
            "confidence": 0.9,
            "decisions": [{"app": "github", "action": "reclaim", "reason": "x"}],
        },
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
    )
    out = policy.intersect_plan(
        plan,
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
        candidates=["github"],
        ticket_apps=["github"],
        notes="",
    )
    assert policy.reclaim_apps(out) == []
    assert policy.hold_apps(out) == ["github"]


def test_auto_reclaim_is_not_a_silent_bypass():
    """auto_reclaim is a planner hint; policy still requires a reclaim decision."""
    assert APPS["github"].get("auto_reclaim") is False
    findings = [{"app": "github", "status": "active"}]
    candidates = policy.candidate_apps(
        apps_config=APPS,
        findings=findings,
        ticket_apps=["github"],
    )
    plan = policy.empty_plan("SUP-10", "leaver@ohmgym.com", reason="no_tool_use")
    out = policy.intersect_plan(
        plan,
        issue_key="SUP-10",
        user_email="leaver@ohmgym.com",
        candidates=candidates,
        ticket_apps=["github"],
        notes="",
    )
    assert policy.reclaim_apps(out) == []
    assert policy.hold_apps(out) == ["github"]
