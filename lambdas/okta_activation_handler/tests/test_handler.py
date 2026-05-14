"""Unit tests for the reactive okta_activation_handler Lambda.

Focused coverage on the FAILURE-outcome filter added 2026-05-14, plus
regression coverage for the existing SUCCESS-path and lastLogin dedup.
"""
from __future__ import annotations

import requests_mock

import handler


OKTA_BASE = "https://test.okta.com"


def _wrap(events: list[dict]) -> dict:
    """Match the Okta event-hook envelope: {data: {events: [...]}}."""
    return {"data": {"events": events}}


def _mock_okta_token(rm: requests_mock.Mocker) -> None:
    rm.post(
        f"{OKTA_BASE}/oauth2/v1/token",
        json={"access_token": "ya29.fake", "token_type": "Bearer", "expires_in": 3600},
    )


def _mock_okta_user(rm: requests_mock.Mocker, user_id: str, last_login: str | None) -> None:
    rm.get(
        f"{OKTA_BASE}/api/v1/users/{user_id}",
        json={"id": user_id, "lastLogin": last_login, "profile": {}},
    )


def _mock_slack(rm: requests_mock.Mocker) -> None:
    rm.post("https://slack.com/api/conversations.create", json={"ok": True, "channel": {"id": "C_TEST"}})
    rm.post("https://slack.com/api/chat.postMessage", json={"ok": True, "ts": "1700000000.000100"})


def test_failure_outcome_event_is_skipped_without_okta_or_slack_calls(reset_token_cache, event_factory):
    """The bug this fixes: Okta emits user.account.update_password for every
    password-policy rejection during activation. Without the FAILURE filter,
    the reactive Lambda calls Okta for lastLogin (sees null), then posts to
    Slack — producing a spurious '✅ activated' message for a hire who simply
    fat-fingered their password.
    """
    failure_event = event_factory(outcome_result="FAILURE", login="priya@ohmgym.com")
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)  # token endpoint stays mocked so we can ASSERT it was never hit
        _mock_slack(rm)
        result = handler._handle_event_post(_wrap([failure_event]))

    assert result["posted"] == []
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "outcome_failure"
    assert result["skipped"][0]["login"] == "priya@ohmgym.com"

    # Critical: no Okta API call (saves rate-limit budget) and no Slack post.
    history_urls = [r.url for r in rm.request_history]
    assert not any("api/v1/users" in u for u in history_urls)
    assert not any("chat.postMessage" in u for u in history_urls)


def test_success_outcome_first_activation_still_posts(reset_token_cache, event_factory):
    """Regression: the SUCCESS path with no prior lastLogin must still post."""
    success_event = event_factory(
        outcome_result="SUCCESS",
        user_id="00uSUCC",
        login="success@ohmgym.com",
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_user(rm, "00uSUCC", last_login=None)
        _mock_slack(rm)
        result = handler._handle_event_post(_wrap([success_event]))

    assert len(result["posted"]) == 1
    assert result["posted"][0]["login"] == "success@ohmgym.com"
    assert result["skipped"] == []


def test_success_outcome_with_prior_login_skipped(reset_token_cache, event_factory):
    """Regression: routine password rotation (lastLogin populated) still skipped."""
    rotate_event = event_factory(
        outcome_result="SUCCESS",
        user_id="00uROT",
        login="veteran@ohmgym.com",
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_user(rm, "00uROT", last_login="2026-01-01T00:00:00.000Z")
        _mock_slack(rm)
        result = handler._handle_event_post(_wrap([rotate_event]))

    assert result["posted"] == []
    assert len(result["skipped"]) == 1
    assert "not_first_activation:already_logged_in" in result["skipped"][0]["reason"]


def test_mixed_batch_failure_then_success(reset_token_cache, event_factory):
    """The real Priya 2026-05-14 sequence: one FAILURE event then one SUCCESS,
    3s apart, both with lastLogin still null. Before the fix this produced two
    Slack posts; after the fix only the SUCCESS posts.
    """
    failure = event_factory(
        outcome_result="FAILURE",
        user_id="00uPRIYA",
        login="priya@ohmgym.com",
        published="2026-05-14T20:57:52.706Z",
    )
    success = event_factory(
        outcome_result="SUCCESS",
        user_id="00uPRIYA",
        login="priya@ohmgym.com",
        published="2026-05-14T20:57:55.912Z",
    )
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_okta_user(rm, "00uPRIYA", last_login=None)
        _mock_slack(rm)
        result = handler._handle_event_post(_wrap([failure, success]))

    assert len(result["posted"]) == 1
    assert result["posted"][0]["login"] == "priya@ohmgym.com"
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["reason"] == "outcome_failure"

    # Only ONE chat.postMessage call (for the SUCCESS event). FAILURE was dropped.
    post_calls = [r for r in rm.request_history if "chat.postMessage" in r.url]
    assert len(post_calls) == 1


def test_unwatched_event_type_still_skipped(reset_token_cache, event_factory):
    """Regression: non-password events still get skipped silently."""
    other = event_factory(event_type="user.lifecycle.activate", outcome_result="SUCCESS")
    with requests_mock.Mocker() as rm:
        _mock_okta_token(rm)
        _mock_slack(rm)
        result = handler._handle_event_post(_wrap([other]))

    assert result["posted"] == []
    assert result["skipped"][0]["reason"] == "not_watched"
