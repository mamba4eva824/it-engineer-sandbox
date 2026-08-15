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
    exact = next(
        (
            item for item in matches
            if (item.get("emailAddress") or "").lower() == email_l and item.get("accountId")
        ),
        None,
    )
    hit = exact or (matches[0] if matches else None)
    # Account-exists: any result for the query counts; prefer exact email when present.
    if hit:
        result = finding(
            app="jira",
            status="active",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=200,
        )
        if hit.get("accountId"):
            result["account_id"] = str(hit["accountId"])
        return result
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


def lookup_account_id(
    *,
    email: str,
    token: str,
    auth_email: str,
    cloud_id: str,
) -> tuple[str | None, dict[str, Any] | None]:
    """Return (accountId, error_finding). error_finding is set when lookup fails."""
    scan = scan_jira(
        email=email,
        token=token,
        auth_email=auth_email,
        cloud_id=cloud_id,
    )
    if scan.get("status") == "error":
        return None, scan
    account_id = scan.get("account_id")
    if account_id:
        return str(account_id), None
    return None, None


def deactivate_user(
    *,
    email: str,
    write_token: str,
    read_token: str,
    auth_email: str,
    cloud_id: str,
) -> dict[str, Any]:
    """Deactivate via Atlassian User Management API (org admin Bearer token).

    Lookup uses the Jira gateway + read token (account-exists). Write uses
    POST /users/{accountId}/manage/lifecycle/disable. 200/204/404 are success
    (404 = already deactivated / gone).
    """
    account_id, lookup_error = lookup_account_id(
        email=email,
        token=read_token,
        auth_email=auth_email,
        cloud_id=cloud_id,
    )
    if lookup_error:
        lookup_error["action_hint"] = ACTION_HINT
        return lookup_error
    if not account_id:
        return finding(
            app="jira",
            status="reclaimed",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=200,
            error="Jira account already absent",
        )

    url = f"https://api.atlassian.com/users/{account_id}/manage/lifecycle/disable"
    try:
        resp = request_with_retry(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {write_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            json={"message": "License reclaim after offboarding"},
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

    if resp.status_code in (200, 204, 404):
        return finding(
            app="jira",
            status="reclaimed",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            http_status=resp.status_code,
        )
    if resp.status_code in (401, 403):
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or (
                f"Jira HTTP {resp.status_code}; org admin API key required for deactivate"
            ),
        )
    error_class = "retryable" if resp.status_code == 429 or resp.status_code >= 500 else "misconfig"
    return finding(
        app="jira",
        status="error",
        seat_type=SEAT_TYPE,
        action_hint=ACTION_HINT,
        error_class=error_class,
        http_status=resp.status_code,
        retryable=error_class == "retryable",
        error=truncate_error(resp.text) or f"Jira HTTP {resp.status_code}",
    )


def product_access_groups(spec: dict[str, Any]) -> list[tuple[str, str | None]]:
    """Groups `remove_product_access` must delete the account from.

    Prefers `product_groups` (name + id per product). Falls back to the
    single `product_group` / `product_group_id` pair used before Confluence.
    """
    raw = spec.get("product_groups")
    if isinstance(raw, list) and raw:
        out: list[tuple[str, str | None]] = []
        for item in raw:
            if isinstance(item, dict):
                name = str(item.get("name") or "").strip()
                gid = item.get("id")
                if name or gid:
                    out.append((name, str(gid) if gid else None))
            elif isinstance(item, str) and item.strip():
                out.append((item.strip(), None))
        if out:
            return out
    name = str(spec.get("product_group") or "jira-users-buffett-dev")
    gid = spec.get("product_group_id")
    return [(name, str(gid) if gid else None)]


def _classify_group_delete(resp: requests.Response) -> dict[str, Any]:
    if resp.status_code in (200, 204, 404):
        return finding(
            app="jira",
            status="reclaimed",
            seat_type=SEAT_TYPE,
            action_hint="remove_product_access",
            http_status=resp.status_code,
        )
    if resp.status_code == 400:
        body = (resp.text or "").lower()
        if "not a member" in body or "not in the group" in body or "not in this group" in body:
            return finding(
                app="jira",
                status="reclaimed",
                seat_type=SEAT_TYPE,
                action_hint="remove_product_access",
                http_status=resp.status_code,
            )
    if resp.status_code in (401, 403):
        return finding(
            app="jira",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint="remove_product_access",
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or (
                f"Jira HTTP {resp.status_code}; token needs manage:jira-configuration scope + site admin"
            ),
        )
    error_class = "retryable" if resp.status_code == 429 or resp.status_code >= 500 else "misconfig"
    return finding(
        app="jira",
        status="error",
        seat_type=SEAT_TYPE,
        action_hint="remove_product_access",
        error_class=error_class,
        http_status=resp.status_code,
        retryable=error_class == "retryable",
        error=truncate_error(resp.text) or f"Jira HTTP {resp.status_code}",
    )


def remove_product_access(
    *,
    email: str,
    write_token: str,
    read_token: str,
    auth_email: str,
    cloud_id: str,
    group_name: str | None = None,
    group_id: str | None = None,
    groups: list[tuple[str, str | None]] | None = None,
) -> dict[str, Any]:
    """Revoke product access by removing the account from configured groups.

    Fallback for sites without org-admin API access (personal / non-domain-claimed
    sites): DELETE /rest/api/3/group/user via the standard gateway + a Basic-auth
    token scoped `manage:jira-configuration`, instead of the org-admin
    lifecycle/disable endpoint that `deactivate_user` uses. 200/204/404 are success
    (404 = user already not in the group, or already gone entirely). Jira Cloud
    returns 400 "is not a member of the group" for the same case — also treated
    as idempotent reclaimed so the broker does not fall through to deactivate_user.

    Prefers `groupId` when provided (Cloud deprecated `groupname`). Walks every
    group in `groups` (Jira Software + Confluence on buffett-dev). One group's
    failure is returned and remaining groups are not claimed as reclaimed.
    """
    targets = groups or [(group_name or "jira-users-buffett-dev", group_id)]
    account_id, lookup_error = lookup_account_id(
        email=email,
        token=read_token,
        auth_email=auth_email,
        cloud_id=cloud_id,
    )
    if lookup_error:
        lookup_error["action_hint"] = "remove_product_access"
        return lookup_error
    if not account_id:
        return finding(
            app="jira",
            status="reclaimed",
            seat_type=SEAT_TYPE,
            action_hint="remove_product_access",
            http_status=200,
            error="Jira account already absent",
        )

    url = f"{gateway_base(cloud_id)}/rest/api/3/group/user"
    last: dict[str, Any] | None = None
    removed: list[str] = []
    for name, gid in targets:
        params: dict[str, str] = {"accountId": account_id}
        if gid:
            params["groupId"] = gid
        else:
            params["groupname"] = name
        label = name or gid or "group"
        try:
            resp = request_with_retry(
                "DELETE",
                url,
                params=params,
                auth=_auth(auth_email, write_token),
                headers={"Accept": "application/json"},
                timeout=15,
            )
        except (requests.Timeout, requests.ConnectionError) as exc:
            return finding(
                app="jira",
                status="error",
                seat_type=SEAT_TYPE,
                action_hint="remove_product_access",
                error_class="retryable",
                retryable=True,
                error=f"{label}: {exc}",
            )
        outcome = _classify_group_delete(resp)
        if outcome.get("status") != "reclaimed":
            err = outcome.get("error") or f"Jira HTTP {outcome.get('http_status')}"
            outcome["error"] = truncate_error(f"{label}: {err}")
            return outcome
        removed.append(label)
        last = outcome
    if last is not None:
        last["removed_groups"] = removed
    return last or finding(
        app="jira",
        status="error",
        seat_type=SEAT_TYPE,
        action_hint="remove_product_access",
        error_class="misconfig",
        retryable=False,
        error="no product-access group configured",
    )
