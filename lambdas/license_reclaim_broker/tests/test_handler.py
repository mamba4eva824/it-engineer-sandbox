"""Broker Lambda handler tests: auth, allowlist, GSI lookup, idempotency,
per-app partial failure, dry-run no-op, and the P3-R5 "never revoke error /
identity_unresolved" refusal.
"""
from __future__ import annotations

import json

import requests_mock

from conftest import GATEWAY, TEST_ORG, make_row

import handler


def test_unauthorized_missing_header(lambda_url_event):
    event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["github"]}, auth=None)
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 401


def test_unauthorized_wrong_secret(lambda_url_event):
    event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["github"]}, auth="wrong")
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 401


def test_method_not_allowed(lambda_url_event):
    event = lambda_url_event(method="GET")
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 405


def test_unknown_app_rejected_400_no_calls(lambda_url_event, table):
    with requests_mock.Mocker() as rm:
        event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["figjam"]})
        resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    assert "unknown app" in json.loads(resp["body"])["error"]
    assert rm.request_history == []


def test_disabled_app_rejected_400(lambda_url_event):
    event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["figma"]})
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 400
    assert "disabled app" in json.loads(resp["body"])["error"]


def test_missing_issue_key_returns_400(lambda_url_event):
    event = lambda_url_event(body={"apps": ["github"]})
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 400


def test_no_findings_row_returns_404(lambda_url_event, table):
    event = lambda_url_event(body={"issue_key": "SUP-999", "apps": ["github"]})
    resp = handler.lambda_handler(event, None)
    assert resp["statusCode"] == 404


def test_dry_run_plan_no_calls_and_no_ddb_write(lambda_url_event, table):
    row = make_row(
        issue_key="SUP-2",
        apps=[
            {"app": "github", "status": "active"},
            {"app": "linear", "status": "not_member"},
            {"app": "jira", "status": "error", "error_class": "misconfig"},
        ],
    )
    table.put_item(Item=row)

    with requests_mock.Mocker() as rm:
        event = lambda_url_event(body={
            "issue_key": "SUP-2",
            "apps": ["github", "linear", "jira"],
            "dry_run": True,
        })
        resp = handler.lambda_handler(event, None)

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    outcomes = {p["app"]: p["outcome"] for p in body["plan"]}
    assert outcomes["github"] == "eligible"
    assert outcomes["linear"] == "not_active_in_findings"
    # P3-R5: an app whose scan status is "error" must never be eligible.
    assert outcomes["jira"] == "not_active_in_findings"
    assert rm.request_history == []
    assert table.get_item(Key={"run_date": row["run_date"], "user_id": row["user_id"]})["Item"].get("reclaim") is None


def test_dry_run_is_the_default_when_flag_omitted(lambda_url_event, table):
    row = make_row(issue_key="SUP-2", apps=[{"app": "github", "status": "active"}])
    table.put_item(Item=row)
    with requests_mock.Mocker() as rm:
        event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["github"]})
        resp = handler.lambda_handler(event, None)
    body = json.loads(resp["body"])
    assert body["dry_run"] is True
    assert rm.request_history == []


def test_already_reclaimed_app_is_idempotent_skip(lambda_url_event, table):
    row = make_row(
        issue_key="SUP-2",
        apps=[{"app": "github", "status": "active"}],
        reclaim=[{"app": "github", "status": "reclaimed"}],
    )
    table.put_item(Item=row)
    with requests_mock.Mocker() as rm:
        event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["github"], "dry_run": False})
        resp = handler.lambda_handler(event, None)
    body = json.loads(resp["body"])
    assert body["results"] == [{"app": "github", "outcome": "already_reclaimed"}]
    assert rm.request_history == []


def test_live_apply_all_succeed_sets_row_status_reclaimed(lambda_url_event, table):
    row = make_row(issue_key="SUP-2", apps=[{"app": "github", "status": "active"}])
    table.put_item(Item=row)

    with requests_mock.Mocker() as rm:
        rm.delete(f"https://api.github.com/orgs/{TEST_ORG}/memberships/marcusreyes", status_code=204)
        event = lambda_url_event(body={
            "issue_key": "SUP-2",
            "apps": ["github"],
            "dry_run": False,
            "requested_by": "chris@ohmgym.com",
        })
        resp = handler.lambda_handler(event, None)

    body = json.loads(resp["body"])
    assert resp["statusCode"] == 200
    assert body["row_status"] == "reclaimed"
    assert body["results"][0]["status"] == "reclaimed"
    stored = table.get_item(Key={"run_date": row["run_date"], "user_id": row["user_id"]})["Item"]
    assert stored["status"] == "reclaimed"
    assert stored["reclaimed_by"] == "chris@ohmgym.com"
    assert stored["reclaim"][0]["app"] == "github"


def test_live_apply_partial_failure_sets_row_status_partial(lambda_url_event, table):
    row = make_row(
        issue_key="SUP-2",
        apps=[
            {"app": "github", "status": "active"},
            {"app": "linear", "status": "active"},
        ],
    )
    table.put_item(Item=row)

    with requests_mock.Mocker() as rm:
        rm.delete(f"https://api.github.com/orgs/{TEST_ORG}/memberships/marcusreyes", status_code=204)
        rm.post("https://api.linear.app/graphql", exc=__import__("requests").exceptions.Timeout)
        event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["github", "linear"], "dry_run": False})
        resp = handler.lambda_handler(event, None)

    body = json.loads(resp["body"])
    assert body["row_status"] == "partial"
    by_app = {r["app"]: r for r in body["results"]}
    assert by_app["github"]["status"] == "reclaimed"
    assert by_app["linear"]["status"] == "error"
    assert by_app["linear"]["error_class"] == "retryable"


def test_jira_tries_remove_product_access_then_deactivate_user(lambda_url_event, table):
    row = make_row(issue_key="SUP-2", apps=[{"app": "jira", "status": "active"}])
    table.put_item(Item=row)

    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": row["login"]}])
        rm.delete(f"{GATEWAY}/rest/api/3/group/user", status_code=204)
        event = lambda_url_event(body={"issue_key": "SUP-2", "apps": ["jira"], "dry_run": False})
        resp = handler.lambda_handler(event, None)

    body = json.loads(resp["body"])
    assert body["results"][0]["status"] == "reclaimed"
    assert body["results"][0]["action_hint"] == "remove_product_access"
    # remove_product_access succeeded, so deactivate_user's lifecycle endpoint
    # must never have been called.
    called_urls = [h.url for h in rm.request_history]
    assert not any("manage/lifecycle/disable" in u for u in called_urls)
