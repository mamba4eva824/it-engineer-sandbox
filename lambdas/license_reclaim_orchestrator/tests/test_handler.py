"""Orchestrator handler tests: mocked OpenAI + mocked broker HTTP."""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest
import requests
import requests_mock

import handler
from conftest import (
    BROKER_URL,
    OPENAI_URL,
    WEBHOOK_SECRET,
    make_row,
    mock_openai,
    mock_slack,
    openai_response,
    ticket_fields,
)

ISSUE_KEY = "SUP-10"


def _eb_event(issue_key: str = ISSUE_KEY, dry_run: bool = False) -> dict:
    return {
        "version": "0",
        "source": "ohmgym.licenses",
        "detail-type": "license.scan.complete",
        "detail": {
            "issue_key": issue_key,
            "run_date": "2026-08-14",
            "user_id": "00u1",
            "okta_id": "00u1",
            "login": "leaver@ohmgym.com",
            "run_id": "run-1",
            "status": "ticketed",
            "dry_run": dry_run,
        },
    }


def _cli_event(issue_key: str = ISSUE_KEY, dry_run: bool = False) -> dict:
    return {"issue_key": issue_key, "dry_run": dry_run, "source": "cli"}


def _jira_patches(fields: dict):
    return (
        patch.object(handler, "get_issue", return_value=(200, fields)),
        patch.object(handler, "add_comment", return_value=(201, {"id": "c1"})),
        patch.object(handler, "transition_to_done", return_value=True),
        patch.object(
            handler,
            "list_transitions",
            return_value=(
                200,
                [{"id": "31", "name": "Done", "to": {"statusCategory": {"key": "done"}}}],
            ),
        ),
        patch.object(handler, "transition_issue", return_value=204),
    )


def _openai_payloads(rm) -> list[dict]:
    return [
        h.json()
        for h in rm.request_history
        if h.url.rstrip("/").endswith("/responses")
    ]


def test_eventbridge_noop_when_auto_run_false(monkeypatch):
    monkeypatch.setattr(handler, "ORCHESTRATOR_AUTO_RUN", "false")
    with patch.object(handler, "openai_plan") as plan:
        result = handler.lambda_handler(_eb_event(), None)
    assert result["skipped"] is True
    plan.assert_not_called()


def test_cli_runs_even_when_auto_run_false(table, monkeypatch):
    monkeypatch.setattr(handler, "ORCHESTRATOR_AUTO_RUN", "false")
    table.put_item(Item=make_row())
    fields = ticket_fields()
    with requests_mock.Mocker() as rm:
        mock_openai(rm)
        mock_slack(rm)
        rm.post(BROKER_URL, json={"event": "license_reclaim_plan", "plan": []})
        g, c, done_p, tr, x = _jira_patches(fields)
        with g, c, done_p as done_mock, tr, x:
            result = handler.lambda_handler(_cli_event(dry_run=True), None)
            done_mock.assert_not_called()
    assert result.get("skipped") is not True
    assert result.get("done") is not True
    assert result["issue_key"] == ISSUE_KEY


def test_fixture_sup_2_is_refused():
    with patch.object(handler, "openai_plan") as plan:
        with requests_mock.Mocker() as rm:
            result = handler.lambda_handler(_cli_event("SUP-2"), None)
    assert result["refused"] is True
    assert result["error_class"] == "fixture"
    plan.assert_not_called()
    assert rm.request_history == []


def test_missing_row_raises():
    with pytest.raises(RuntimeError, match="no findings"):
        handler.lambda_handler(_cli_event("SUP-999"), None)


def test_happy_path_reclaims_github_and_jira_then_done(table, capsys):
    table.put_item(Item=make_row())
    fields = ticket_fields()
    live = {
        "event": "license_reclaim_complete",
        "results": [
            {"app": "github", "status": "reclaimed"},
            {"app": "jira", "status": "reclaimed"},
        ],
    }
    with requests_mock.Mocker() as rm:
        mock_openai(rm)
        mock_slack(rm)
        rm.post(
            BROKER_URL,
            [
                {"json": {"event": "license_reclaim_plan", "dry_run": True, "plan": []}},
                {"json": live},
            ],
        )
        g, c, done_p, tr, x = _jira_patches(fields)
        with g, c, done_p as done_mock, tr, x:
            result = handler.lambda_handler(_cli_event(dry_run=False), None)
            done_mock.assert_called_once()

    assert result["done"] is True
    assert set(result["reclaim_apps"]) == {"github", "jira"}
    assert result["usage"]["input_tokens"] == 412
    assert result["usage"]["output_tokens"] == 86
    assert result["usage"]["total_tokens"] == 498
    assert isinstance(result["usage"]["latency_ms"], int)
    assert result["usage_missing"] is False
    payloads = _openai_payloads(rm)
    assert len(payloads) == 1
    assert payloads[0]["model"] == "gpt-5.6-luna"
    assert payloads[0]["max_output_tokens"] == 512
    assert payloads[0]["tool_choice"]["type"] == "function"
    assert payloads[0]["tool_choice"]["name"] == "submit_reclaim_plan"
    assert payloads[0]["reasoning"]["effort"] == "low"
    assert "reasoning_effort" not in payloads[0]
    assert "messages" not in payloads[0]
    assert payloads[0]["tools"][0]["name"] == "submit_reclaim_plan"
    assert "additionalModelRequestFields" not in payloads[0]
    dumped = json.dumps(payloads[0])
    assert "bedrock" not in dumped.lower()

    broker_posts = [h for h in rm.request_history if h.url.rstrip("/") == BROKER_URL.rstrip("/")]
    assert len(broker_posts) == 2
    assert broker_posts[0].json()["dry_run"] is True
    assert broker_posts[1].json()["dry_run"] is False
    for post in broker_posts:
        body = post.json()
        assert body["issue_key"] == ISSUE_KEY
        assert body["requested_by"] == "orchestrator@ohmgym.com"
        assert set(body["apps"]) == {"github", "jira"}
        assert post.headers["Authorization"] == WEBHOOK_SECRET

    stored = table.get_item(Key={"run_date": "2026-08-14", "user_id": "00u1"})["Item"]
    assert stored["planner"]["input_tokens"] == 412
    assert stored["planner"]["output_tokens"] == 86
    assert stored["planner"]["total_tokens"] == 498
    assert stored["planner"]["model_id"] == "gpt-5.6-luna"

    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert any(e.get("event") == "reclaim_plan" and e.get("input_tokens") == 412 for e in logs)


def test_missing_usage_still_reclaims_and_logs_flag(table, capsys):
    table.put_item(Item=make_row())
    fields = ticket_fields()
    live = {
        "event": "license_reclaim_complete",
        "results": [
            {"app": "github", "status": "reclaimed"},
            {"app": "jira", "status": "reclaimed"},
        ],
    }
    with requests_mock.Mocker() as rm:
        mock_openai(rm, openai_response(include_usage=False))
        mock_slack(rm)
        rm.post(BROKER_URL, [{"json": {"dry_run": True}}, {"json": live}])
        g, c, done_p, tr, x = _jira_patches(fields)
        with g, c, done_p, tr, x:
            result = handler.lambda_handler(_cli_event(dry_run=False), None)
    assert result["reclaim_apps"]
    assert result["usage_missing"] is True
    assert result["usage"]["input_tokens"] == 0
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.startswith("{")]
    assert any(e.get("usage_missing") for e in logs)


def test_legal_hold_notes_skip_live_broker(table):
    table.put_item(Item=make_row())
    fields = ticket_fields(notes="Legal hold — do not reclaim")
    with requests_mock.Mocker() as rm:
        mock_openai(rm)
        mock_slack(rm)
        g, c, done_p, tr, trans = _jira_patches(fields)
        with g, c, done_p as done_mock, tr, trans as trans_mock:
            result = handler.lambda_handler(_cli_event(dry_run=False), None)
            trans_mock.assert_not_called()
            done_mock.assert_not_called()
    assert result["done"] is False
    assert result["reclaim_apps"] == []
    assert set(result["hold_apps"]) == {"github", "jira"}
    broker_posts = [h for h in rm.request_history if h.url.rstrip("/") == BROKER_URL.rstrip("/")]
    assert broker_posts == []


def test_linear_error_github_only_in_candidates(table):
    table.put_item(Item=make_row(apps=[
        {"app": "github", "status": "active"},
        {"app": "linear", "status": "error", "error_class": "retryable"},
        {"app": "jira", "status": "not_member"},
    ]))
    fields = ticket_fields(apps="github, linear")
    live = {"event": "license_reclaim_complete", "results": [{"app": "github", "status": "reclaimed"}]}
    with requests_mock.Mocker() as rm:
        mock_openai(rm, openai_response(apps=["github"]))
        mock_slack(rm)
        rm.post(BROKER_URL, [{"json": {"dry_run": True}}, {"json": live}])
        g, c, done_p, tr, x = _jira_patches(fields)
        with g, c, done_p, tr, x:
            result = handler.lambda_handler(_cli_event(dry_run=False), None)
    assert result["candidates"] == ["github"]
    user_text = _openai_payloads(rm)[0]["input"]
    parsed = json.loads(user_text)
    assert parsed["candidates"] == ["github"]
    broker_posts = [h for h in rm.request_history if h.url.rstrip("/") == BROKER_URL.rstrip("/")]
    assert broker_posts[-1].json()["apps"] == ["github"]


def test_hallucinated_figma_and_email_never_reach_broker(table):
    table.put_item(Item=make_row())
    fields = ticket_fields()
    bogus = openai_response(
        user_email="other@ohmgym.com",
        extra_decisions=[{"app": "figma", "action": "reclaim", "reason": "hallucinated"}],
    )
    with requests_mock.Mocker() as rm:
        mock_openai(rm, bogus)
        mock_slack(rm)
        g, c, done_p, tr, x = _jira_patches(fields)
        with g, c, done_p, tr, x:
            result = handler.lambda_handler(_cli_event(dry_run=False), None)
    assert result["reclaim_apps"] == []
    assert "figma" not in result.get("reclaim_apps", [])
    broker_posts = [h for h in rm.request_history if h.url.rstrip("/") == BROKER_URL.rstrip("/")]
    assert broker_posts == []


def test_openai_timeout_comments_deferred_and_does_not_revoke(table):
    table.put_item(Item=make_row())
    fields = ticket_fields()
    with requests_mock.Mocker() as rm:
        rm.post(OPENAI_URL, exc=requests.Timeout("read timed out"))
        g, c, done_p, tr, trans = _jira_patches(fields)
        with g as _g, c as comment_mock, done_p as done_mock, tr as _tr, trans as trans_mock:
            with pytest.raises(RuntimeError, match="openai timeout"):
                handler.lambda_handler(_cli_event(dry_run=False), None)
            comment = comment_mock.call_args.kwargs.get("text") or (
                comment_mock.call_args[1].get("text") if comment_mock.call_args else ""
            )
            assert "deferred" in comment.lower()
            trans_mock.assert_not_called()
        broker_posts = [h for h in rm.request_history if h.url.rstrip("/") == BROKER_URL.rstrip("/")]
        assert broker_posts == []


def test_west_region_defaults():
    assert handler.SECRETS_REGION == "us-west-1"
    assert handler.OPENAI_MODEL_ID == "gpt-5.6-luna"
    assert handler.OPENAI_BASE_URL == "https://api.openai.com/v1"
    assert not hasattr(handler, "_bedrock")


def test_transition_to_done_walks_start_then_resolved():
    """JSM To Do has no direct Done; walker must Start then Resolved."""
    import jira_client

    cloud = "test-cloud-id"
    issue = "SUP-10"
    base = f"https://api.atlassian.com/ex/jira/{cloud}/rest/api/3/issue/{issue}"
    todo = {"fields": {"status": {"name": "To Do", "statusCategory": {"key": "new"}}}}
    start = {
        "id": "81",
        "name": "Start",
        "to": {"id": "3", "name": "In Progress", "statusCategory": {"key": "indeterminate"}},
    }
    resolved = {
        "id": "121",
        "name": "Resolved",
        "to": {"id": "10082", "name": "Done", "statusCategory": {"key": "done"}},
    }
    with requests_mock.Mocker() as rm:
        rm.get(base, json=todo)
        rm.get(
            f"{base}/transitions",
            [
                {"json": {"transitions": [start]}},
                {"json": {"transitions": [resolved]}},
            ],
        )
        rm.post(f"{base}/transitions", status_code=204)
        ok = jira_client.transition_to_done(
            cloud_id=cloud, auth_email="it-ops@example.com", token="t", issue_key=issue,
        )
    assert ok is True
    posts = [h for h in rm.request_history if h.method == "POST"]
    assert [h.json()["transition"]["id"] for h in posts] == ["81", "121"]


def test_transition_to_done_already_done_is_success():
    import jira_client

    cloud = "test-cloud-id"
    issue = "SUP-10"
    base = f"https://api.atlassian.com/ex/jira/{cloud}/rest/api/3/issue/{issue}"
    done = {"fields": {"status": {"name": "Done", "statusCategory": {"key": "done"}}}}
    with requests_mock.Mocker() as rm:
        rm.get(base, json=done)
        ok = jira_client.transition_to_done(
            cloud_id=cloud, auth_email="it-ops@example.com", token="t", issue_key=issue,
        )
    assert ok is True
    assert [h.method for h in rm.request_history] == ["GET"]
