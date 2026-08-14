"""Connector HTTP classification (ADR-011) — GitHub / Linear / Jira."""
from __future__ import annotations

import requests
import requests_mock

from conftest import GATEWAY, LINEAR_ORG, TEST_ORG
from github_client import scan_github
from jira_client import scan_jira
from linear_client import scan_linear


def test_github_404_is_not_member():
    with requests_mock.Mocker() as rm:
        rm.get(
            f"https://api.github.com/orgs/{TEST_ORG}/members/octocat",
            status_code=404,
        )
        result = scan_github(org=TEST_ORG, token="t", login="octocat")
    assert result["status"] == "not_member"
    assert result["http_status"] == 404
    assert result["error_class"] is None


def test_github_401_is_misconfig_not_not_member():
    with requests_mock.Mocker() as rm:
        rm.get(
            f"https://api.github.com/orgs/{TEST_ORG}/members/octocat",
            status_code=401,
            text="Bad credentials",
        )
        result = scan_github(org=TEST_ORG, token="t", login="octocat")
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"
    assert result["http_status"] == 401
    assert result["status"] != "not_member"


def test_github_missing_login_is_identity_unresolved_no_http():
    with requests_mock.Mocker() as rm:
        result = scan_github(org=TEST_ORG, token="t", login=None)
    assert result["status"] == "error"
    assert result["error_class"] == "identity_unresolved"
    assert result["retryable"] is False
    assert rm.request_history == []


def test_jira_site_url_is_misconfig_401():
    site = "https://buffett-dev.atlassian.net"
    with requests_mock.Mocker() as rm:
        rm.get(
            f"{site}/rest/api/3/user/search",
            status_code=401,
            text="Unauthorized",
        )
        result = scan_jira(
            email="marcus.reyes@ohmgym.com",
            token="t",
            auth_email="ops@example.com",
            base_url=site,
        )
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"
    assert result["http_status"] == 401
    assert result["status"] != "not_member"


def test_jira_gateway_empty_search_is_not_member():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[])
        result = scan_jira(
            email="marcus.reyes@ohmgym.com",
            token="t",
            auth_email="ops@example.com",
            cloud_id="test-cloud-id",
        )
    assert result["status"] == "not_member"


def test_jira_missing_cloud_id_is_misconfig():
    result = scan_jira(
        email="marcus.reyes@ohmgym.com",
        token="t",
        auth_email="ops@example.com",
        cloud_id=None,
    )
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"


def test_linear_timeout_is_retryable():
    with requests_mock.Mocker() as rm:
        rm.post("https://api.linear.app/graphql", exc=requests.exceptions.Timeout)
        result = scan_linear(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "error"
    assert result["error_class"] == "retryable"
    assert result["retryable"] is True


def test_linear_wrong_org_is_misconfig():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            json={
                "data": {
                    "organization": {"id": "00000000-0000-0000-0000-000000000000"},
                    "users": {"nodes": []},
                }
            },
        )
        result = scan_linear(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["error_class"] == "misconfig"
    assert result["status"] == "error"


def test_linear_human_email_active_is_member():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            json={
                "data": {
                    "organization": {"id": LINEAR_ORG},
                    "users": {
                        "nodes": [
                            {"email": "bot@linear.app", "active": True},
                            {"email": "marcus.reyes@ohmgym.com", "active": True},
                        ]
                    },
                }
            },
        )
        result = scan_linear(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "active"
