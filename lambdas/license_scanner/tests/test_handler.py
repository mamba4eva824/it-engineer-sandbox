"""Unit tests for the license_scanner Lambda handler (Phase 2 exit criteria)."""
from __future__ import annotations

import json
import re
from unittest.mock import patch

import pytest
import requests
import requests_mock

import handler
from conftest import GATEWAY, LINEAR_ORG, TEST_ORG

RUN_DATE = "2026-08-14"
EMAIL = "marcus.reyes@ohmgym.com"
OKTA_ID = "00uMARCUS"
RUN_ID = "run-1"
ISSUE_POST = re.compile(rf"{re.escape(GATEWAY)}/rest/api/3/issue$")
ISSUE_COMMENT = re.compile(r".*/rest/api/3/issue/.+/comment$")
ISSUE_PUT = re.compile(rf"{re.escape(GATEWAY)}/rest/api/3/issue/SUP-\d+$")
SEARCH = re.compile(r".*/rest/api/3/search")
USER_SEARCH = re.compile(r".*/rest/api/3/user/search")
GITHUB_MEMBER = re.compile(rf"https://api.github.com/orgs/{TEST_ORG}/members/.+")


def _event(**overrides) -> dict:
    payload = {
        "user_email": EMAIL,
        "okta_id": OKTA_ID,
        "run_id": RUN_ID,
        "run_date": RUN_DATE,
        "github_username": "octocat",
    }
    payload.update(overrides)
    return payload


def _eb_event(detail: dict, dry_run: bool = False) -> dict:
    ev = {
        "version": "0",
        "source": "ohmgym.offboarding",
        "detail-type": "leaver.completed",
        "detail": detail,
    }
    if dry_run:
        ev["dry_run"] = True
    return ev


def _mock_slack(rm: requests_mock.Mocker, *, ok: bool = True) -> None:
    rm.post(
        "https://slack.com/api/conversations.create",
        json={"ok": True, "channel": {"id": "C_TEST"}},
    )
    if ok:
        rm.post(
            "https://slack.com/api/chat.postMessage",
            json={"ok": True, "ts": "1700000000.000100"},
        )
    else:
        rm.post(
            "https://slack.com/api/chat.postMessage",
            json={"ok": False, "error": "internal_error"},
        )


def _mock_linear_absent(rm: requests_mock.Mocker) -> None:
    rm.post(
        "https://api.linear.app/graphql",
        json={
            "data": {
                "organization": {"id": LINEAR_ORG},
                "users": {"nodes": [{"email": "bot@linear.app", "active": True}]},
            }
        },
    )


def _mock_jira_not_member(rm: requests_mock.Mocker) -> None:
    rm.get(USER_SEARCH, json=[])


def _mock_jira_create(rm: requests_mock.Mocker, *, status: int = 201, key: str = "SUP-10") -> None:
    rm.get(SEARCH, json={"issues": []})
    rm.post(ISSUE_POST, status_code=status, json={"id": "10100", "key": key} if status < 400 else {"error": "fail"})
    rm.post(ISSUE_COMMENT, status_code=201, json={"id": "c1"})
    rm.put(ISSUE_PUT, status_code=204)


def _mock_github(rm: requests_mock.Mocker, status: int = 404) -> None:
    rm.get(GITHUB_MEMBER, status_code=status)


def _issue_creates(rm: requests_mock.Mocker) -> list:
    return [r for r in rm.request_history if r.method == "POST" and ISSUE_POST.fullmatch(r.url.split("?")[0])]


def test_github_401_tickets_and_does_not_raise(empty_table):
    """Connector misconfig is ticketed; Lambda must not raise (no SNS)."""
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 401)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-401")
        _mock_slack(rm)
        result = handler.lambda_handler(_event(), None)
    assert result["status"] == "partial"
    github = next(a for a in result["apps"] if a["app"] == "github")
    assert github["error_class"] == "misconfig"
    assert github["status"] == "error"
    assert result["jira_issue_key"] == "SUP-401"
    linear = next(a for a in result["apps"] if a["app"] == "linear")
    assert linear["status"] == "not_member"


def test_github_401_does_not_skip_linear_or_jira(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 401)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-12")
        _mock_slack(rm)
        handler.lambda_handler(_event(), None)
    assert any("api.linear.app" in (r.url or "") for r in rm.request_history)
    assert any("user/search" in (r.url or "") for r in rm.request_history)


def test_http_does_not_retry_401():
    from http_util import request_with_retry

    with requests_mock.Mocker() as rm:
        rm.get("https://example.test/401", status_code=401, text="nope")
        resp = request_with_retry("GET", "https://example.test/401", max_attempts=3)
    assert resp.status_code == 401
    assert len(rm.request_history) == 1


def test_http_retries_500_then_returns():
    from http_util import request_with_retry

    with requests_mock.Mocker() as rm:
        rm.get(
            "https://example.test/500",
            [
                {"status_code": 500, "text": "blip"},
                {"status_code": 200, "text": "ok"},
            ],
        )
        resp = request_with_retry("GET", "https://example.test/500", max_attempts=3)
    assert resp.status_code == 200
    assert len(rm.request_history) == 2


def test_clean_user_no_ticket(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 404)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_slack(rm)
        result = handler.lambda_handler(_event(), None)
    assert result["status"] == "clean"
    assert result["jira_issue_key"] is None
    assert _issue_creates(rm) == []
    item = empty_table.get_item(Key={"run_date": RUN_DATE, "user_id": OKTA_ID})["Item"]
    assert item["status"] == "clean"
    figma = next(a for a in result["apps"] if a["app"] == "figma")
    assert figma["status"] == "skipped"


def test_github_active_opens_ticket_without_figma(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 204)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-42")
        _mock_slack(rm)
        result = handler.lambda_handler(_event(), None)
    assert result["status"] == "ticketed"
    assert result["jira_issue_key"] == "SUP-42"
    creates = _issue_creates(rm)
    assert len(creates) == 1
    body = json.loads(creates[0].text)
    apps_field = body["fields"]["customfield_10141"]
    assert "github" in apps_field
    assert "figma" not in apps_field
    assert body["fields"]["customfield_10010"] == "4"


def test_identity_unresolved_tickets_without_github_http(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-7")
        _mock_slack(rm)
        result = handler.lambda_handler(_event(github_username=None), None)
    assert any(a["app"] == "github" and a["error_class"] == "identity_unresolved" for a in result["apps"])
    assert not any("api.github.com" in (r.url or "") for r in rm.request_history)
    assert len(_issue_creates(rm)) == 1
    assert result["status"] in ("partial", "error")
    slack_posts = [
        r for r in rm.request_history
        if r.method == "POST" and "chat.postMessage" in (r.url or "")
    ]
    assert slack_posts
    slack_body = json.loads(slack_posts[0].text)
    slack_text = json.dumps(slack_body)
    assert "*Identity:* github" in slack_text
    assert "Okta githubUsername empty; GitHub membership not scanned" in slack_text
    assert "*Errors:* none" in slack_text
    assert "error (identity_unresolved)" not in slack_text
    creates = _issue_creates(rm)
    jsm = json.loads(creates[0].text)
    assert "Identity:" in json.dumps(jsm)
    assert "Scan errors:" not in json.dumps(jsm)


def test_linear_timeout_github_active_is_partial_one_ticket(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 204)
        rm.post("https://api.linear.app/graphql", exc=requests.exceptions.Timeout)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-11")
        _mock_slack(rm)
        result = handler.lambda_handler(_event(), None)
    assert result["status"] == "partial"
    linear = next(a for a in result["apps"] if a["app"] == "linear")
    github = next(a for a in result["apps"] if a["app"] == "github")
    assert linear["error_class"] == "retryable"
    assert github["status"] == "active"
    assert len(_issue_creates(rm)) == 1


def test_duplicate_invoke_comments_existing_ticket(empty_table):
    empty_table.put_item(Item={
        "run_date": RUN_DATE,
        "user_id": OKTA_ID,
        "login": EMAIL,
        "status": "ticketed",
        "jira_issue_key": "SUP-9",
        "ttl_epoch": 99999999999,
    })
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 204)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, key="SUP-99")
        _mock_slack(rm)
        result = handler.lambda_handler(_event(), None)
    assert result["jira_issue_key"] == "SUP-9"
    assert _issue_creates(rm) == []
    assert any(ISSUE_COMMENT.search(r.url or "") for r in rm.request_history if r.method == "POST")


def test_jsm_create_500_persists_error_and_raises(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 204)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_jira_create(rm, status=500)
        _mock_slack(rm)
        with pytest.raises(RuntimeError, match="work_queue"):
            handler.lambda_handler(_event(), None)
    item = empty_table.get_item(Key={"run_date": RUN_DATE, "user_id": OKTA_ID})["Item"]
    assert item["status"] == "error"
    assert item["error_class"] == "work_queue"
    assert any("chat.postMessage" in (r.url or "") for r in rm.request_history)


def test_invalid_payload_raises_infra():
    with pytest.raises(ValueError):
        handler.lambda_handler({}, None)


def test_fetch_secret_missing_raises():
    with pytest.raises(Exception):
        handler._fetch_secret("does-not-exist")


def test_slack_failure_does_not_raise_on_clean(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 404)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_slack(rm, ok=False)
        result = handler.lambda_handler(_event(), None)
    assert result["status"] == "clean"
    assert result["slack"]["posted"] is False


def test_dry_run_skips_jira_ddb_slack(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 204)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        result = handler.lambda_handler(_event(dry_run=True), None)
    assert result["dry_run"] is True
    assert result["ticket_wanted"] is True
    assert _issue_creates(rm) == []
    assert "Item" not in empty_table.get_item(Key={"run_date": RUN_DATE, "user_id": OKTA_ID})
    assert not any("chat.postMessage" in (r.url or "") for r in rm.request_history)


def test_eventbridge_envelope(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 404)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_slack(rm)
        result = handler.lambda_handler(_eb_event(_event()), None)
    assert result["status"] == "clean"


def test_all_connectors_failed_raises(empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 500)
        rm.post("https://api.linear.app/graphql", exc=requests.exceptions.Timeout)
        rm.get(USER_SEARCH, status_code=503, text="unavailable")
        _mock_jira_create(rm, key="SUP-8")
        _mock_slack(rm)
        with pytest.raises(RuntimeError, match="all_connectors_failed"):
            handler.lambda_handler(_event(), None)
    item = empty_table.get_item(Key={"run_date": RUN_DATE, "user_id": OKTA_ID})["Item"]
    assert item["status"] == "error"
    assert item["error_class"] == "all_connectors_failed"
    assert item.get("jira_issue_key") == "SUP-8"


@patch.object(handler, "persist_findings", side_effect=RuntimeError("ddb down"))
def test_ddb_failure_raises_infra(_persist, empty_table):
    with requests_mock.Mocker() as rm:
        _mock_github(rm, 404)
        _mock_linear_absent(rm)
        _mock_jira_not_member(rm)
        _mock_slack(rm)
        with pytest.raises(RuntimeError, match="infra"):
            handler.lambda_handler(_event(), None)
