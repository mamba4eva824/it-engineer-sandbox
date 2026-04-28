"""POST helpers for Slack Web API.

The shared client in _client.py only exposes GET via call(). Mover needs
chat.postMessage and conversations.open, which require POST with a JSON body.
Same auth + error shape as _client, just the other HTTP verb.

Slack treats chat.postMessage as accepting either form-encoded or JSON, but
JSON is cleaner and plays better with block kit payloads.
"""

import os
import time

import requests

from _client import SlackAPIError, api_url


def session_for_token(token: str) -> requests.Session:
    """Build a Session authenticated with an arbitrary Slack token (xoxp- or xoxb-).

    Callers who want the default user session can keep using _client.get_session();
    this helper is for scripts that hold multiple tokens — e.g., a user token for
    admin.* calls plus a bot token for workspace-scoped chat.postMessage.
    """
    if not token:
        raise ValueError("session_for_token requires a non-empty token")
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    return session


def bot_session_if_configured() -> requests.Session | None:
    """Returns a Session for SLACK_BOT_TOKEN if set, else None."""
    tok = (os.getenv("SLACK_BOT_TOKEN", "") or "").strip().strip('"')
    if not tok:
        return None
    return session_for_token(tok)


def post(
    session: requests.Session,
    method_path: str,
    body: dict,
    max_retries: int = 3,
) -> dict:
    """POST with JSON body; handle Slack's {ok:false} envelope and 429 retries."""
    url = api_url(method_path)
    headers = {"Content-Type": "application/json; charset=utf-8"}
    for attempt in range(max_retries + 1):
        resp = session.post(url, json=body, headers=headers, timeout=30)
        if resp.status_code == 429:
            if attempt >= max_retries:
                resp.raise_for_status()
            time.sleep(int(resp.headers.get("Retry-After", "1")))
            continue
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise SlackAPIError(method_path, payload.get("error", "unknown"), payload)
        return payload
    return {}  # unreachable


def lookup_user_id_by_email(session: requests.Session, email: str) -> str:
    """users.lookupByEmail is a GET; wrap it here so Mover has one place to look.

    Raises SlackAPIError with error="users_not_found" if the email isn't a
    Slack user (common on Enterprise Grid if SCIM hasn't run yet).
    """
    url = api_url("users.lookupByEmail")
    resp = session.get(url, params={"email": email}, timeout=15)
    resp.raise_for_status()
    payload = resp.json()
    if not payload.get("ok"):
        raise SlackAPIError("users.lookupByEmail", payload.get("error", "unknown"), payload)
    return payload["user"]["id"]


def open_dm_channel(session: requests.Session, slack_user_id: str) -> str:
    """conversations.open returns the IM channel id for DMing a user."""
    payload = post(session, "conversations.open", {"users": slack_user_id})
    return payload["channel"]["id"]


def post_message(session: requests.Session, channel: str, text: str, blocks: list | None = None) -> str:
    """chat.postMessage. Returns the posted message ts (useful for threading/audit)."""
    body: dict = {"channel": channel, "text": text}
    if blocks:
        body["blocks"] = blocks
    payload = post(session, "chat.postMessage", body)
    return payload.get("ts", "")


def resolve_channel_id(session: requests.Session, channel_name: str) -> str:
    """Resolve a channel name to its id.

    Tries `conversations.list` first (standard user-token path). On Enterprise
    Grid tokens `conversations.list` often returns `missing_argument` (it wants
    a team_id), so we fall back to `admin.conversations.search` when available
    (requires `admin.conversations:read`). Either path accepts channel names
    with or without the leading '#'.
    """
    wanted = channel_name.lstrip("#")

    # Path 1: conversations.list (works on workspace-scoped user tokens)
    try:
        cursor = ""
        while True:
            params = {"limit": "200", "types": "public_channel,private_channel"}
            if cursor:
                params["cursor"] = cursor
            resp = session.get(api_url("conversations.list"), params=params, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
            if not payload.get("ok"):
                raise SlackAPIError("conversations.list", payload.get("error", "unknown"), payload)
            for ch in payload.get("channels", []):
                if ch.get("name") == wanted:
                    return ch["id"]
            cursor = payload.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                break
    except SlackAPIError as e:
        # Fall through to admin path on Enterprise Grid scope shapes.
        if e.error not in ("missing_argument", "missing_scope", "team_not_found"):
            raise

    # Path 2: admin.conversations.search (Enterprise Grid fallback)
    cursor = ""
    while True:
        params = {"limit": "100", "query": wanted}
        if cursor:
            params["cursor"] = cursor
        resp = session.get(api_url("admin.conversations.search"), params=params, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        if not payload.get("ok"):
            raise SlackAPIError("admin.conversations.search", payload.get("error", "unknown"), payload)
        for ch in payload.get("conversations", []):
            if ch.get("name") == wanted and not ch.get("is_archived"):
                return ch["id"]
        cursor = payload.get("next_cursor") or payload.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            raise SlackAPIError("admin.conversations.search", "channel_not_found", {"name": channel_name})
