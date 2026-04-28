"""Shared Slack API client used by every script in scripts/slack/.

Handles:
  - Authentication via SLACK_USER_TOKEN (xoxp-) from the project .env
  - Slack's "HTTP 200 with {ok: false}" error shape (unlike normal REST)
  - Rate limiting via the Retry-After header
  - Cursor pagination (response_metadata.next_cursor)
  - Dual base URLs: Web API at slack.com/api/ and Audit Logs at api.slack.com/audit/v1/

Mirrors the scripts/okta/_client.py shape: get_session() returns an authenticated
requests.Session; api_url() composes URLs; paginate() yields items from cursor-paginated
endpoints.
"""

import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv


load_dotenv(Path(__file__).parent.parent.parent / ".env")

SLACK_USER_TOKEN = os.getenv("SLACK_USER_TOKEN", "").strip().strip('"')
SLACK_ENTERPRISE_ID = os.getenv("SLACK_ENTERPRISE_ID", "").strip().strip('"')

WEB_API_BASE = "https://slack.com/api"
AUDIT_API_BASE = "https://api.slack.com/audit/v1"


class SlackAPIError(Exception):
    """Slack returned HTTP 200 but {'ok': false}."""

    def __init__(self, method: str, error: str, response_body: dict):
        self.method = method
        self.error = error
        self.response_body = response_body
        super().__init__(f"Slack API {method} failed: {error}")


def _require(name: str, value: str) -> str:
    if not value:
        print(f"ERROR: {name} missing from .env")
        sys.exit(1)
    return value


def get_session() -> requests.Session:
    """Build an authenticated requests.Session for Slack API calls."""
    _require("SLACK_USER_TOKEN", SLACK_USER_TOKEN)
    if not SLACK_USER_TOKEN.startswith("xoxp-"):
        print(f"ERROR: SLACK_USER_TOKEN must start with xoxp- (got {SLACK_USER_TOKEN[:5]}-)")
        print("       Bot tokens (xoxb-) cannot call admin.* or auditlogs:read APIs.")
        sys.exit(1)
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {SLACK_USER_TOKEN}",
        "Accept": "application/json",
    })
    return session


def api_url(path: str, audit: bool = False) -> str:
    """Compose a Slack API URL. audit=True routes to the Audit Logs API base."""
    base = AUDIT_API_BASE if audit else WEB_API_BASE
    return f"{base}/{path.lstrip('/')}"


def call(
    session: requests.Session,
    method_path: str,
    params: dict | None = None,
    audit: bool = False,
    max_retries: int = 3,
) -> dict:
    """Execute a GET request against Slack's API with its quirks handled.

    - HTTP 200 with {"ok": false, "error": "..."} raises SlackAPIError
    - HTTP 429 with Retry-After header sleeps then retries (up to max_retries)
    - Returns the parsed JSON body on success
    """
    url = api_url(method_path, audit=audit)
    for attempt in range(max_retries + 1):
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 429:
            if attempt >= max_retries:
                resp.raise_for_status()
            retry_after = int(resp.headers.get("Retry-After", "1"))
            time.sleep(retry_after)
            continue
        resp.raise_for_status()
        # Audit API returns straight JSON on success; Web API uses the ok envelope.
        # Audit API errors come through as HTTP 4xx/5xx (raise_for_status above).
        body = resp.json()
        if audit:
            return body
        if not body.get("ok"):
            raise SlackAPIError(method_path, body.get("error", "unknown"), body)
        return body
    return {}  # unreachable


def paginate(
    session: requests.Session,
    method_path: str,
    params: dict | None = None,
    audit: bool = False,
    items_key: str = "entries",
):
    """Yield items from a cursor-paginated Slack endpoint.

    Both Web API and Audit API use response_metadata.next_cursor. Pass items_key
    matching the payload's collection field ("entries" for audit logs, "members"
    for users.list, "channels" for conversations.list, etc.).
    """
    next_params = dict(params or {})
    while True:
        body = call(session, method_path, params=next_params, audit=audit)
        for item in body.get(items_key, []):
            yield item
        cursor = body.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            return
        next_params["cursor"] = cursor
