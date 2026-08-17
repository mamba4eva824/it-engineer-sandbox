"""GitHub org membership scan. 204=active, 404=not_member, empty login=not_assigned, 401/403=misconfig."""
from __future__ import annotations

from typing import Any

import requests

from http_util import finding, request_with_retry, truncate_error

SEAT_TYPE = "org_member"
ACTION_HINT = "remove_org_member"


def scan_github(*, org: str, token: str, login: str | None) -> dict[str, Any]:
    if not (login or "").strip():
        return finding(
            app="github",
            status="not_assigned",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error="No GitHub username on Okta profile; membership not queried",
        )

    url = f"https://api.github.com/orgs/{org}/members/{login.strip()}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = request_with_retry("GET", url, headers=headers, timeout=10)
    except (requests.Timeout, requests.ConnectionError) as exc:
        return finding(
            app="github",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            retryable=True,
            error=str(exc),
        )

    if resp.status_code == 204:
        return finding(
            app="github",
            status="active",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=204,
        )
    if resp.status_code == 404:
        return finding(
            app="github",
            status="not_member",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=404,
        )
    if resp.status_code in (401, 403):
        return finding(
            app="github",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or f"GitHub HTTP {resp.status_code}",
        )
    error_class = "retryable" if resp.status_code == 429 or resp.status_code >= 500 else "misconfig"
    return finding(
        app="github",
        status="error",
        seat_type=SEAT_TYPE,
        action_hint=ACTION_HINT,
        error_class=error_class,
        http_status=resp.status_code,
        retryable=error_class == "retryable",
        error=truncate_error(resp.text) or f"GitHub HTTP {resp.status_code}",
    )


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def remove_org_member(*, org: str, token: str, login: str | None) -> dict[str, Any]:
    """Remove org membership (and pending invites). 204=removed, 404=already gone."""
    if not (login or "").strip():
        return finding(
            app="github",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="identity_unresolved",
            retryable=False,
            error="Okta githubUsername empty; GitHub membership not revoked",
        )

    url = f"https://api.github.com/orgs/{org}/memberships/{login.strip()}"
    try:
        resp = request_with_retry("DELETE", url, headers=_github_headers(token), timeout=10)
    except (requests.Timeout, requests.ConnectionError) as exc:
        return finding(
            app="github",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            retryable=True,
            error=str(exc),
        )

    if resp.status_code in (204, 404):
        return finding(
            app="github",
            status="reclaimed",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=resp.status_code,
        )
    if resp.status_code in (401, 403):
        return finding(
            app="github",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or f"GitHub HTTP {resp.status_code}",
        )
    error_class = "retryable" if resp.status_code == 429 or resp.status_code >= 500 else "misconfig"
    return finding(
        app="github",
        status="error",
        seat_type=SEAT_TYPE,
        action_hint=ACTION_HINT,
        error_class=error_class,
        http_status=resp.status_code,
        retryable=error_class == "retryable",
        error=truncate_error(resp.text) or f"GitHub HTTP {resp.status_code}",
    )
