"""Unit tests for the onboarding_workflow Lambda handler.

All AWS calls go through moto (set up in conftest.py). Okta + Slack HTTP
calls are mocked via requests_mock per test. No live network or AWS.
"""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import pytest
import requests_mock
from freezegun import freeze_time

import handler


TODAY = "2026-05-14"  # frozen by @freeze_time on the relevant tests
OKTA_BASE = "https://test.okta.com"


def _mock_okta_token(rm: requests_mock.Mocker) -> None:
    rm.post(
        f"{OKTA_BASE}/oauth2/v1/token",
        json={"access_token": "ya29.fake", "token_type": "Bearer", "expires_in": 3600},
    )


def _mock_okta_search(rm: requests_mock.Mocker, users: list[dict]) -> None:
    rm.get(f"{OKTA_BASE}/api/v1/users", json=users)


def _mock_okta_activate(rm: requests_mock.Mocker, user_id: str, status: int = 200, body: dict | None = None) -> None:
    rm.post(
        f"{OKTA_BASE}/api/v1/users/{user_id}/lifecycle/activate",
        status_code=status,
        json=body if body is not None else {},
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
def test_search_url_includes_today_pt(reset_token_cache, empty_audit_table):
    """The Okta search query is built from today_PT, URL-encoded by requests."""
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [])
        _mock_slack(rm)
        handler.lambda_handler({}, None)
        search_req = next(r for r in rm.request_history if r.url.startswith(f"{OKTA_BASE}/api/v1/users") and r.method == "GET")
        qs = parse_qs(urlparse(search_req.url).query)
        assert qs["search"][0] == f'status eq "STAGED" and profile.startDate eq "{TODAY}"'
        assert qs["limit"][0] == "200"


def test_override_date_takes_precedence(reset_token_cache, empty_audit_table):
    """event['override_date'] beats wall-clock today."""
    override = "2026-04-01"
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [])
        _mock_slack(rm)
        handler.lambda_handler({"override_date": override}, None)
        search_req = next(r for r in rm.request_history if r.url.startswith(f"{OKTA_BASE}/api/v1/users"))
        qs = parse_qs(urlparse(search_req.url).query)
        assert override in qs["search"][0]


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_activate_called_for_each_user(reset_token_cache, empty_audit_table, okta_user_factory):
    """For N STAGED matches, N activate POSTs fire (idempotency guard not triggered)."""
    users = [
        okta_user_factory(user_id=f"00u{i:03d}", login=f"hire{i}@ohmgym.com", start_date=TODAY)
        for i in range(3)
    ]
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, users)
        for u in users:
            _mock_okta_activate(rm, u["id"])
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    assert result["activated_count"] == 3
    assert result["error_count"] == 0
    activate_calls = [r for r in rm.request_history if "lifecycle/activate" in r.url]
    assert len(activate_calls) == 3
    for r in activate_calls:
        assert "sendEmail=true" in r.url


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_dynamodb_idempotency_guard(reset_token_cache, empty_audit_table, okta_user_factory):
    """If a success row already exists for (today, user_id), skip the activate POST."""
    users = [
        okta_user_factory(user_id="00uA", login="a@ohmgym.com", start_date=TODAY),
        okta_user_factory(user_id="00uB", login="b@ohmgym.com", start_date=TODAY),
        okta_user_factory(user_id="00uC", login="c@ohmgym.com", start_date=TODAY),
    ]
    # Pre-seed 00uA as already-activated today.
    empty_audit_table.put_item(Item={
        "run_date": TODAY, "user_id": "00uA", "login": "a@ohmgym.com",
        "status": "success", "okta_response_status": 200, "ttl_epoch": 99999999999,
    })

    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, users)
        _mock_okta_activate(rm, "00uB")
        _mock_okta_activate(rm, "00uC")
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    activate_calls = [r for r in rm.request_history if "lifecycle/activate" in r.url]
    assert len(activate_calls) == 2
    # URL shape: .../users/{id}/lifecycle/activate?... — user_id is 3 segments back.
    assert {urlparse(r.url).path.split("/")[-3] for r in activate_calls} == {"00uB", "00uC"}
    assert result["skipped_count"] == 1
    assert result["skipped"][0]["user_id"] == "00uA"


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_dynamodb_record_attributes(reset_token_cache, empty_audit_table, okta_user_factory):
    """A successful activation writes the full identity snapshot to DynamoDB."""
    user = okta_user_factory(
        user_id="00uXYZ",
        login="priya@ohmgym.com",
        first_name="Priya",
        last_name="Patel",
        department="Data",
        role_title="Data Engineer",
        start_date=TODAY,
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_okta_activate(rm, "00uXYZ")
        _mock_slack(rm)
        handler.lambda_handler({}, None)
    row = empty_audit_table.get_item(Key={"run_date": TODAY, "user_id": "00uXYZ"})["Item"]
    assert row["login"] == "priya@ohmgym.com"
    assert row["first_name"] == "Priya"
    assert row["last_name"] == "Patel"
    assert row["department"] == "Data"
    assert row["role_title"] == "Data Engineer"
    assert row["start_date"] == TODAY
    assert row["status"] == "success"
    assert int(row["okta_response_status"]) == 200
    assert row["error_message"] == ""
    assert "timestamp_utc" in row
    assert "batch_run_id" in row
    # TTL ~90 days out.
    assert int(row["ttl_epoch"]) > 0


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_dynamodb_error_record(reset_token_cache, empty_audit_table, okta_user_factory):
    """Okta 5xx → audit row records status=error with the Okta errorSummary."""
    user = okta_user_factory(user_id="00uERR", login="err@ohmgym.com", start_date=TODAY)
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_okta_activate(rm, "00uERR", status=500, body={
            "errorCode": "E0000009",
            "errorSummary": "Internal Server Error",
        })
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    row = empty_audit_table.get_item(Key={"run_date": TODAY, "user_id": "00uERR"})["Item"]
    assert row["status"] == "error"
    assert int(row["okta_response_status"]) == 500
    assert "Internal Server Error" in row["error_message"]
    assert result["error_count"] == 1
    assert result["activated_count"] == 0


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_slack_batch_summary_blocks(reset_token_cache, empty_audit_table, okta_user_factory):
    """Block Kit payload renders the activated list with name/role/dept/login."""
    user = okta_user_factory(
        user_id="00uSL",
        login="sl@ohmgym.com",
        first_name="Marcus",
        last_name="Reyes",
        department="Data",
        role_title="Data Analyst",
        start_date=TODAY,
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [user])
        _mock_okta_activate(rm, "00uSL")
        _mock_slack(rm)
        handler.lambda_handler({}, None)
        post_call = next(r for r in rm.request_history if r.url.endswith("/api/chat.postMessage"))
    payload = json.loads(post_call.text)
    assert payload["channel"] == "C_TEST"
    assert "Daily joiner activations" in payload["text"]
    # Render with ensure_ascii=False so the rocket glyph stays in plain UTF-8.
    flat = json.dumps(payload["blocks"], ensure_ascii=False)
    assert "🚀 Daily joiner activations" in flat
    assert "Marcus Reyes" in flat
    assert "Data Analyst" in flat
    assert "Data" in flat
    assert "sl@ohmgym.com" in flat
    assert "batch_run_id" in flat


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_zero_staged_users_today(reset_token_cache, empty_audit_table):
    """Empty Okta search → no activate calls, no DynamoDB writes, Slack still posts the summary."""
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [])
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    assert result["activated_count"] == 0
    assert result["error_count"] == 0
    assert result["skipped_count"] == 0
    assert not any("lifecycle/activate" in r.url for r in rm.request_history)
    # Slack post still goes out (with a "0 activated" body).
    assert any(r.url.endswith("/api/chat.postMessage") for r in rm.request_history)


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_okta_jwt_token_cached_across_users(reset_token_cache, empty_audit_table, okta_user_factory):
    """Token exchange happens exactly once for a batch of N users."""
    users = [
        okta_user_factory(user_id=f"00u{i:03d}", login=f"u{i}@ohmgym.com", start_date=TODAY)
        for i in range(4)
    ]
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, users)
        for u in users:
            _mock_okta_activate(rm, u["id"])
        _mock_slack(rm)
        handler.lambda_handler({}, None)
    token_calls = [r for r in rm.request_history if r.url.endswith("/oauth2/v1/token")]
    assert len(token_calls) == 1


@freeze_time(f"{TODAY}T16:00:00+00:00")
def test_handler_returns_summary_on_partial_failure(reset_token_cache, empty_audit_table, okta_user_factory):
    """One success + one Okta-error → handler returns the summary, doesn't raise."""
    ok_user = okta_user_factory(user_id="00uOK", login="ok@ohmgym.com", start_date=TODAY)
    bad_user = okta_user_factory(user_id="00uBAD", login="bad@ohmgym.com", start_date=TODAY)
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_search(rm, [ok_user, bad_user])
        _mock_okta_activate(rm, "00uOK", status=200)
        _mock_okta_activate(rm, "00uBAD", status=400, body={
            "errorCode": "E0000001", "errorSummary": "Bad request",
        })
        _mock_slack(rm)
        result = handler.lambda_handler({}, None)
    assert result["activated_count"] == 1
    assert result["error_count"] == 1
    assert result["activated"][0]["login"] == "ok@ohmgym.com"
    assert result["errors"][0]["login"] == "bad@ohmgym.com"


def test_okta_search_failure_raises(reset_token_cache, empty_audit_table):
    """If the Okta search HTTP call fails, the Lambda raises so CloudWatch records an error."""
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        rm.get(f"{OKTA_BASE}/api/v1/users", status_code=502, json={"errorSummary": "bad gateway"})
        with pytest.raises(Exception):
            handler.lambda_handler({}, None)
