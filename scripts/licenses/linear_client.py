"""Linear workspace membership scan. Ignore *.linear.app identities; wrong org is misconfig."""
from __future__ import annotations

from typing import Any

import requests

from http_util import finding, request_with_retry, truncate_error

SEAT_TYPE = "workspace_member"
ACTION_HINT = "suspend_user"
DEFAULT_ORG_UUID = "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"
GRAPHQL_URL = "https://api.linear.app/graphql"
QUERY = """
query LicenseScanUsers {
  organization { id }
  users {
    nodes {
      email
      active
    }
  }
}
"""


def scan_linear(
    *,
    api_key: str,
    email: str,
    expected_org_uuid: str = DEFAULT_ORG_UUID,
) -> dict[str, Any]:
    headers = {
        "Authorization": api_key,
        "Content-Type": "application/json",
    }
    try:
        resp = request_with_retry(
            "POST",
            GRAPHQL_URL,
            headers=headers,
            json={"query": QUERY},
            timeout=15,
        )
    except (requests.Timeout, requests.ConnectionError) as exc:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            retryable=True,
            error=str(exc),
        )

    if resp.status_code in (401, 403):
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or f"Linear HTTP {resp.status_code}",
        )
    if resp.status_code == 429 or resp.status_code >= 500:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            http_status=resp.status_code,
            retryable=True,
            error=truncate_error(resp.text) or f"Linear HTTP {resp.status_code}",
        )
    if resp.status_code != 200:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=truncate_error(resp.text) or f"Linear HTTP {resp.status_code}",
        )

    try:
        body = resp.json()
    except ValueError:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            http_status=resp.status_code,
            retryable=True,
            error="Linear GraphQL transport failure: non-JSON body",
        )

    gql_errors = body.get("errors") or []
    data = body.get("data") or {}
    if gql_errors and not data:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="retryable",
            http_status=resp.status_code,
            retryable=True,
            error=truncate_error(str(gql_errors[0])) or "Linear GraphQL transport failure",
        )

    org_id = (data.get("organization") or {}).get("id")
    if org_id and org_id != expected_org_uuid:
        return finding(
            app="linear",
            status="error",
            seat_type=SEAT_TYPE,
            action_hint=ACTION_HINT,
            error_class="misconfig",
            http_status=resp.status_code,
            retryable=False,
            error=f"Linear viewer org {org_id} != {expected_org_uuid}",
        )

    nodes = ((data.get("users") or {}).get("nodes")) or []
    email_l = email.lower()
    for node in nodes:
        node_email = (node.get("email") or "").lower()
        if not node_email or node_email.endswith(".linear.app"):
            continue
        if node_email == email_l and node.get("active"):
            return finding(
                app="linear",
                status="active",
                seat_type=SEAT_TYPE,
                action_hint=ACTION_HINT,
                http_status=resp.status_code,
            )
    return finding(
        app="linear",
        status="not_member",
        seat_type=SEAT_TYPE,
        action_hint=ACTION_HINT,
        http_status=resp.status_code,
    )
