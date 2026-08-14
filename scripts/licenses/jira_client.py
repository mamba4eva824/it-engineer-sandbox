"""Jira account-exists scan via the Atlassian gateway. Site URL 401 is misconfig."""
from __future__ import annotations

from typing import Any

import requests

from http_util import finding, request_with_retry, truncate_error

SEAT_TYPE = "jira_account"
ACTION_HINT = "deactivate_user"
GATEWAY_PREFIX = "https://api.atlassian.com/ex/jira/"


def gateway_base(cloud_id: str) -> str:
    return f"{GATEWAY_PREFIX}{cloud_id}"


def is_site_url(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return ".atlassian.net" in lowered and "api.atlassian.com" not in lowered


def _auth(email: str, token: str) -> tuple[str, str]:
    return (email, token)


def scan_jira(
    *,
    email: str,
    token: str,
    auth_email: str,
    cloud_id: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    if base_url:
        root = base_url.rstrip("/")
    elif cloud_id:
        root = gateway_base(cloud_id)
    else:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            retryable=False,
            error="missing JIRA_CLOUD_ID",
        )

    url = f"{root}/rest/api/3/user/search"
    try:
        resp = request_with_retry(
            "GET",
            url,
            params={"query": email},
            auth=_auth(auth_email, token),
            headers={"Accept": "application/json"},
            timeout=15,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            retryable=True,
            error=str(exc),
        )

    if is_site_url(root):
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or "Jira site URL is misconfig; use api.atlassian.com gateway",
        )

    if resp.status_code == 401:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=401,
            retryable=False,
            error=truncate_error(resp.text) or "Jira HTTP 401",
        )

    if resp.status_code == 429 or resp.status_code >= 500:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            http_status=resp.status_code,
            retryable=True,
            error=truncate_error(resp.text) or f"Jira HTTP {resp.status_code}",
        )

    if resp.status_code != 200:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or f"Jira HTTP {resp.status_code}",
        )

    try:
        accounts = resp.json()
    except ValueError:
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=200,
            error="Jira user search returned non-JSON",
        )

    matches = accounts if isinstance(accounts, list) else []
    email_l = email.lower()
    hit = any(
        (item.get("emailAddress") or "").lower() == email_l
        or (item.get("displayName") and email_l in str(item).lower())
        for item in matches
    )
    # Account-exists: any result for the query counts; prefer exact email when present.
    if not hit and matches:
        hit = True
    if hit:
        return finding(
            app="jira",
            status="active",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=200,
        )
    return finding(
        app="jira",
        status="not_member",
        seat_type=SEAT_TYPE,
        action_hint=ACTION_HINT,
        http_status=200,
    )


def adf_doc(text: str) -> dict[str, Any]:
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text or " "}],
            }
        ],
    }


def _jira_headers() -> dict[str, str]:
    return {"Accept": "application/json", "Content-Type": "application/json"}


def create_issue(
    *,
    cloud_id: str,
    auth_email: str,
    token: str,
    fields: dict[str, Any],
) -> tuple[int, dict[str, Any]]:
    url = f"{gateway_base(cloud_id)}/rest/api/3/issue"
    resp = request_with_retry(
        "POST",
        url,
        auth=_auth(auth_email, token),
        headers=_jira_headers(),
        json={"fields": fields},
        timeout=15,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {"error": truncate_error(resp.text)}
    return resp.status_code, body


def search_issues(
    *,
    cloud_id: str,
    auth_email: str,
    token: str,
    jql: str,
) -> tuple[int, list[dict[str, Any]]]:
    url = f"{gateway_base(cloud_id)}/rest/api/3/search"
    resp = request_with_retry(
        "GET",
        url,
        auth=_auth(auth_email, token),
        headers={"Accept": "application/json"},
        params={"jql": jql, "maxResults": 5, "fields": "key,summary"},
        timeout=15,
    )
    if resp.status_code != 200:
        return resp.status_code, []
    try:
        body = resp.json()
    except ValueError:
        return resp.status_code, []
    return resp.status_code, body.get("issues") or []


def add_comment(
    *,
    cloud_id: str,
    auth_email: str,
    token: str,
    issue_key: str,
    text: str,
) -> tuple[int, dict[str, Any]]:
    url = f"{gateway_base(cloud_id)}/rest/api/3/issue/{issue_key}/comment"
    resp = request_with_retry(
        "POST",
        url,
        auth=_auth(auth_email, token),
        headers=_jira_headers(),
        json={"body": adf_doc(text)},
        timeout=15,
    )
    try:
        body = resp.json()
    except ValueError:
        body = {"error": truncate_error(resp.text)}
    return resp.status_code, body


def update_issue(
    *,
    cloud_id: str,
    auth_email: str,
    token: str,
    issue_key: str,
    fields: dict[str, Any],
) -> int:
    url = f"{gateway_base(cloud_id)}/rest/api/3/issue/{issue_key}"
    resp = request_with_retry(
        "PUT",
        url,
        auth=_auth(auth_email, token),
        headers=_jira_headers(),
        json={"fields": fields},
        timeout=15,
    )
    return resp.status_code
