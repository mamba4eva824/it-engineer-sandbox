"""Unit tests for the offboarding_workflow Lambda handler."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests_mock
from freezegun import freeze_time

import handler

TODAY = "2026-05-14"
OKTA_BASE = "https://test.okta.com"


def _mock_okta_token(rm: requests_mock.Mocker) -> None:
    rm.post(
        f"{OKTA_BASE}/oauth2/v1/token",
        json={"access_token": "ya29.fake", "token_type": "Bearer", "expires_in": 3600},
    )


def _mock_okta_search(rm: requests_mock.Mocker, users: list[dict]) -> None:
    rm.get(f"{OKTA_BASE}/api/v1/users", json=users)


def _mock_sessions(rm: requests_mock.Mocker, user_id: str, status: int = 204) -> None:
    rm.delete(f"{OKTA_BASE}/api/v1/users/{user_id}/sessions", status_code=status)


def _mock_deactivate(rm: requests_mock.Mocker, user_id: str, status: int = 200) -> None:
    rm.post(
        f"{OKTA_BASE}/api/v1/users/{user_id}/lifecycle/deactivate",
        status_code=status,
        json={},
    )


def _mock_slack(rm: requests_mock.Mocker) -> None:
    rm.post(
        "https://slack.com/api/conversations.create",
        json={"ok": True, "channel": {"id": "C_TEST"}},
    )
    rm.post(
        "https://slack.com/api/chat.postMessage",
        json={"ok": True, "ts": "1700000000.000100"},
    )


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_search_includes_end_date(reset_token_cache, empty_audit_table):
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [])
        _mock_slack(rm)
        handler.lambda_handler({}, None)
        search_req = next(
            r for r in rm.request_history
            if r.url.startswith(f"{OKTA_BASE}/api/v1/users") and r.method == "GET"
        )
        qs = parse_qs(urlparse(search_req.url).query)
        assert f'profile.endDate eq "{TODAY}"' in qs["search"][0]
        assert "ACTIVE" in qs["search"][0]


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_deactivate_flow(reset_token_cache, empty_audit_table, okta_user_factory):
    user = okta_user_factory(user_id="00uA", login="a@ohmgym.com", end_date=TODAY)
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_sessions(rm, "00uA")
        _mock_deactivate(rm, "00uA")
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    assert result["deactivated_count"] == 1
    assert result["event"] == "offboarding_batch_complete"
    assert any("lifecycle/deactivate" in r.url for r in rm.request_history)
    assert any(r.method == "DELETE" and "/sessions" in r.url for r in rm.request_history)


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_idempotency_skip(reset_token_cache, empty_audit_table, okta_user_factory):
    user = okta_user_factory(user_id="00uA", login="a@ohmgym.com", end_date=TODAY)
    empty_audit_table.put_item(Item={
        "run_date": TODAY, "user_id": "00uA", "login": "a@ohmgym.com",
        "status": "success", "okta_response_status": 200, "ttl_epoch": 99999999999,
    })
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    assert result["skipped_count"] == 1
    assert not any("lifecycle/deactivate" in r.url for r in rm.request_history)


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_slack_leaver_summary(reset_token_cache, empty_audit_table, okta_user_factory):
    user = okta_user_factory(
        user_id="00uSL", login="alex@ohmgym.com",
        first_name="Alex", last_name="Novak", end_date=TODAY,
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_sessions(rm, "00uSL")
        _mock_deactivate(rm, "00uSL")
        _mock_slack(rm)
        handler.lambda_handler({}, None)
        post = next(r for r in rm.request_history if r.url.endswith("/api/chat.postMessage"))
    payload = json.loads(post.text)
    flat = json.dumps(payload["blocks"], ensure_ascii=False)
    assert "leaver deactivations" in flat.lower()
    assert "Alex Novak" in flat


def test_okta_search_failure_raises(reset_token_cache, empty_audit_table):
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        rm.get(f"{OKTA_BASE}/api/v1/users", status_code=502, json={"errorSummary": "bad gateway"})
        with pytest.raises(Exception):
            handler.lambda_handler({}, None)
