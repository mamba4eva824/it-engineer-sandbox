"""Connector WRITE-function tests (Phase 3) — GitHub / Linear / Jira revoke.

Mirrors lambdas/license_scanner/tests/test_connectors.py's HTTP-classification
style, but for the write path added on top of the read/scan connectors.
Write results use status in {"reclaimed", "error"} — a different vocabulary
than the scan functions' {"active", "not_member", "error"}.
"""
from __future__ import annotations

import requests
import requests_mock

from conftest import GATEWAY, TEST_ORG

from github_client import remove_org_member
from jira_client import deactivate_user, product_access_groups, remove_product_access
from linear_client import suspend_user


# --- GitHub: remove_org_member ---

def test_github_remove_member_204_is_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.delete(f"https://api.github.com/orgs/{TEST_ORG}/memberships/octocat", status_code=204)
        result = remove_org_member(org=TEST_ORG, token="t", login="octocat")
    assert result["status"] == "reclaimed"
    assert result["http_status"] == 204


def test_github_remove_member_404_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.delete(f"https://api.github.com/orgs/{TEST_ORG}/memberships/octocat", status_code=404)
        result = remove_org_member(org=TEST_ORG, token="t", login="octocat")
    assert result["status"] == "reclaimed"


def test_github_remove_member_403_is_misconfig():
    with requests_mock.Mocker() as rm:
        rm.delete(
            f"https://api.github.com/orgs/{TEST_ORG}/memberships/octocat",
            status_code=403,
            text="Must be an org owner",
        )
        result = remove_org_member(org=TEST_ORG, token="t", login="octocat")
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"


def test_github_remove_member_empty_login_is_identity_unresolved_no_http():
    with requests_mock.Mocker() as rm:
        result = remove_org_member(org=TEST_ORG, token="t", login=None)
    assert result["status"] == "error"
    assert result["error_class"] == "identity_unresolved"
    assert rm.request_history == []


# --- Linear: suspend_user ---

def test_linear_suspend_success_is_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            [
                {
                    "json": {
                        "data": {
                            "organization": {"id": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"},
                            "users": {"nodes": [{"id": "u-1", "email": "marcus.reyes@ohmgym.com", "active": True}]},
                        }
                    }
                },
                {"json": {"data": {"userSuspend": {"success": True}}}},
            ],
        )
        result = suspend_user(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "reclaimed"


def test_linear_suspend_already_absent_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            json={
                "data": {
                    "organization": {"id": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"},
                    "users": {"nodes": []},
                }
            },
        )
        result = suspend_user(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "reclaimed"
    # No mutation call should fire when the user is already absent.
    assert len(rm.request_history) == 1


def test_linear_suspend_already_inactive_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            json={
                "data": {
                    "organization": {"id": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"},
                    "users": {"nodes": [{"id": "u-1", "email": "marcus.reyes@ohmgym.com", "active": False}]},
                }
            },
        )
        result = suspend_user(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "reclaimed"
    assert len(rm.request_history) == 1


def test_linear_suspend_mutation_failure_is_misconfig():
    with requests_mock.Mocker() as rm:
        rm.post(
            "https://api.linear.app/graphql",
            [
                {
                    "json": {
                        "data": {
                            "organization": {"id": "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"},
                            "users": {"nodes": [{"id": "u-1", "email": "marcus.reyes@ohmgym.com", "active": True}]},
                        }
                    }
                },
                {"json": {"data": {"userSuspend": {"success": False}}, "errors": [{"message": "not permitted"}]}},
            ],
        )
        result = suspend_user(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"


def test_linear_suspend_timeout_is_retryable():
    with requests_mock.Mocker() as rm:
        rm.post("https://api.linear.app/graphql", exc=requests.exceptions.Timeout)
        result = suspend_user(api_key="k", email="marcus.reyes@ohmgym.com")
    assert result["status"] == "error"
    assert result["error_class"] == "retryable"
    assert result["retryable"] is True


# --- Jira: deactivate_user / remove_product_access ---

def test_jira_remove_product_access_success_is_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(f"{GATEWAY}/rest/api/3/group/user", status_code=204)
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            group_name="jira-servicedesk-users",
        )
    assert result["status"] == "reclaimed"
    assert result["action_hint"] == "remove_product_access"


def test_jira_remove_product_access_prefers_group_id_query_param():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(f"{GATEWAY}/rest/api/3/group/user", status_code=204)
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            group_name="jira-users-buffett-dev",
            group_id="f757c432-6ca9-41a9-b956-e4b9396a1cf9",
        )
    assert result["status"] == "reclaimed"
    qs = rm.request_history[-1].qs
    assert qs["groupid"] == ["f757c432-6ca9-41a9-b956-e4b9396a1cf9"]
    assert "groupname" not in qs


def test_jira_remove_product_access_400_not_a_member_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(
            f"{GATEWAY}/rest/api/3/group/user",
            status_code=400,
            text='{"errorMessages":["User is not a member of the group."]}',
        )
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            group_name="jira-users-buffett-dev",
        )
    assert result["status"] == "reclaimed"
    assert result["http_status"] == 400


def test_jira_remove_product_access_already_absent_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[])
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            group_name="jira-servicedesk-users",
        )
    assert result["status"] == "reclaimed"
    assert rm.request_history[-1].method == "GET"  # never called DELETE


def test_jira_remove_product_access_403_is_misconfig_mentions_scope():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(f"{GATEWAY}/rest/api/3/group/user", status_code=403, text="")
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            group_name="jira-servicedesk-users",
        )
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"
    assert "manage:jira-configuration" in result["error"]


def test_jira_remove_product_access_loops_all_groups_and_stops_on_error():
    groups = [
        ("jira-users-buffett-dev", "gid-jira"),
        ("confluence-users-buffett-dev", "gid-confluence"),
    ]
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(f"{GATEWAY}/rest/api/3/group/user", status_code=204)
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            groups=groups,
        )
    assert result["status"] == "reclaimed"
    assert result["removed_groups"] == ["jira-users-buffett-dev", "confluence-users-buffett-dev"]
    deletes = [h for h in rm.request_history if h.method == "DELETE"]
    assert [h.qs["groupid"][0] for h in deletes] == ["gid-jira", "gid-confluence"]

    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.delete(
            f"{GATEWAY}/rest/api/3/group/user",
            [
                {"status_code": 204},
                {"status_code": 403, "text": ""},
            ],
        )
        result = remove_product_access(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
            groups=groups,
        )
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"
    assert "confluence-users-buffett-dev" in (result.get("error") or "")


def test_product_access_groups_reads_config_list():
    groups = product_access_groups({
        "product_group": "legacy-only",
        "product_group_id": "legacy-id",
        "product_groups": [
            {"name": "jira-users-buffett-dev", "id": "gid-jira"},
            {"name": "confluence-users-buffett-dev", "id": "gid-confluence"},
        ],
    })
    assert groups == [
        ("jira-users-buffett-dev", "gid-jira"),
        ("confluence-users-buffett-dev", "gid-confluence"),
    ]
    assert product_access_groups({
        "product_group": "jira-users-buffett-dev",
        "product_group_id": "gid-jira",
    }) == [("jira-users-buffett-dev", "gid-jira")]


def test_jira_deactivate_user_403_is_misconfig_mentions_org_admin():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.post("https://api.atlassian.com/users/acc-1/manage/lifecycle/disable", status_code=403, text="")
        result = deactivate_user(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
        )
    assert result["status"] == "error"
    assert result["error_class"] == "misconfig"
    assert "org admin" in result["error"]


def test_jira_deactivate_user_404_is_idempotent_reclaimed():
    with requests_mock.Mocker() as rm:
        rm.get(f"{GATEWAY}/rest/api/3/user/search", json=[{"accountId": "acc-1", "emailAddress": "marcus.reyes@ohmgym.com"}])
        rm.post("https://api.atlassian.com/users/acc-1/manage/lifecycle/disable", status_code=404)
        result = deactivate_user(
            email="marcus.reyes@ohmgym.com",
            write_token="wt",
            read_token="rt",
            auth_email="it-ops@example.com",
            cloud_id="test-cloud-id",
        )
    assert result["status"] == "reclaimed"
