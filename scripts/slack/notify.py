"""High-level Slack notification helpers for JML lifecycle events.

Three production-shaped audit posts that the joiner/leaver workflows (and the
Okta event-hook Lambda) call. Each function is idempotent on the channel side
(ensure_channel creates-or-resolves) and returns a structured dict matching the
existing slack_post_audit shape so the JSONL audit log keeps the same schema.

Channel split, by design:
  #joiner-it-ops  — welcome email sent + activation completed
  #leaver-it-ops  — Okta account deactivated

Why two channels: real IT ops separates onboarding chatter (which managers and
recruiters want to see) from offboarding chatter (which security and IT leads
want to see) so each audience can mute the other without missing what they own.

Posting identity: the xoxb- bot token (SLACK_BOT_TOKEN). Channels created by
the bot are auto-joined by the bot. Channels that pre-existed via admin UI
need a one-time `/invite @<bot>` to grant chat:write.

Vendored into the Lambda zip via build.sh — same module, same Slack token shape.
"""

from __future__ import annotations

import os

from _client import SlackAPIError, api_url
from _post import bot_session_if_configured, post, post_message, resolve_channel_id


JOINER_CHANNEL = "joiner-it-ops"
LEAVER_CHANNEL = "leaver-it-ops"


def _resolve_channel_id_with_team(bot_session, name: str, team_id: str) -> str:
    """conversations.list with explicit team_id (required for org-installed bots).

    The shared resolve_channel_id in _post.py is wired for the user token's
    workspace-scoped path or the admin.conversations.search fallback. The bot
    is org-installed so it needs team_id on every conversations.list call.
    """
    # Only public_channel — private requires groups:read which the bot doesn't
    # have (and the joiner/leaver channels are public anyway).
    cursor = ""
    while True:
        params = {"limit": "200", "types": "public_channel", "team_id": team_id}
        if cursor:
            params["cursor"] = cursor
        resp = bot_session.get(api_url("conversations.list"), params=params, timeout=30)
        resp.raise_for_status()
        body = resp.json()
        if not body.get("ok"):
            raise SlackAPIError("conversations.list", body.get("error", "unknown"), body)
        for ch in body.get("channels", []):
            if ch.get("name") == name:
                return ch["id"]
        cursor = body.get("response_metadata", {}).get("next_cursor", "")
        if not cursor:
            break
    raise SlackAPIError("conversations.list", "channel_not_found", {"name": name, "team_id": team_id})


def _workspace_team_id() -> str:
    """Return the workspace team_id (T-prefix) for conversations.create.

    On Enterprise Grid, bot tokens installed at the org level have an
    enterprise_id (E-prefix) returned by auth.test in the `team_id` field —
    that won't work as the team_id argument to conversations.create, which
    needs an actual workspace id (T-prefix). The workspace id is set in
    SLACK_TEAM_ID in .env; resolve once via admin.conversations.search if
    you need to discover it (see notify.py docstring).
    """
    team_id = (os.getenv("SLACK_TEAM_ID", "") or "").strip().strip('"')
    if not team_id:
        raise SlackAPIError(
            "conversations.create", "missing_team_id_env",
            {"hint": "Set SLACK_TEAM_ID=T... (workspace id, NOT enterprise id) in .env"},
        )
    return team_id


def ensure_channel(bot_session, name: str) -> str:
    """Resolve a public channel by name, creating it if it doesn't exist.

    Returns the channel id. Idempotent paths:
      - Channel didn't exist → create it (bot auto-joins what it creates).
      - Channel existed → name_taken → resolve via conversations.list / admin.search,
        then make sure the bot is a member (conversations.join is a no-op if it
        already is).

    Bot must be a member to post via chat.postMessage; `conversations.join`
    handles that idempotently.
    """
    wanted = name.lstrip("#")
    team_id = _workspace_team_id()
    try:
        payload = post(
            bot_session, "conversations.create",
            {"name": wanted, "is_private": False, "team_id": team_id},
        )
        return payload["channel"]["id"]
    except SlackAPIError as e:
        if e.error not in ("name_taken", "channel_name_already_taken"):
            raise
    # Pre-existing channel: resolve via conversations.list (bot has channels:read).
    # Pass team_id explicitly because the bot is org-installed.
    channel_id = _resolve_channel_id_with_team(bot_session, wanted, team_id)
    # Bot may not be a member of a pre-existing channel; join is idempotent.
    try:
        post(bot_session, "conversations.join", {"channel": channel_id})
    except SlackAPIError as e:
        if e.error not in ("already_in_channel", "method_not_supported_for_channel_type"):
            raise
    return channel_id


def _post_block(bot_session, channel_id: str, text: str, fields: list[tuple[str, str]]) -> str:
    """Post a Block Kit message: header line + key:value field pairs.

    `text` becomes the notification fallback (mobile push, screen readers).
    Fields render as a 2-column section block in the Slack UI.
    """
    section_fields = [{"type": "mrkdwn", "text": f"*{k}:*\n{v}"} for k, v in fields]
    blocks = [
        {"type": "section", "text": {"type": "mrkdwn", "text": text}},
        {"type": "section", "fields": section_fields},
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "Posted by NovaTech IT Ops automation"}
        ]},
    ]
    return post_message(bot_session, channel_id, text, blocks=blocks)


def post_joiner_welcome_sent(
    bot_session, full_name: str, login: str, department: str, role_title: str,
    *, dry_run: bool = False, channel_name: str = JOINER_CHANNEL,
) -> dict:
    """Post to #joiner-it-ops when the activation email is dispatched."""
    text = f":incoming_envelope: *Welcome email sent to new hire:* {full_name} ({login})"
    fields = [
        ("Department", department),
        ("Role", role_title),
        ("Login", login),
        ("Status", "Activation email dispatched — awaiting password set"),
    ]
    if dry_run:
        return {"skipped": False, "dry_run": True, "channel_name": channel_name, "text": text}
    if bot_session is None:
        return {"skipped": True, "reason": "no_bot_token"}
    try:
        channel_id = ensure_channel(bot_session, channel_name)
        ts = _post_block(bot_session, channel_id, text, fields)
    except SlackAPIError as e:
        return {"skipped": True, "reason": e.error}
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text}


def post_joiner_activated(
    bot_session, full_name: str, login: str, event_time: str,
    *, dry_run: bool = False, channel_name: str = JOINER_CHANNEL,
) -> dict:
    """Post to #joiner-it-ops when the user completes activation (set password).

    `event_time` is the Okta system-log event timestamp (ISO 8601). Called
    from the Lambda handler when an Okta event hook fires for
    user.account.update_password.
    """
    text = f":white_check_mark: *New hire activated Okta:* {full_name} ({login})"
    fields = [
        ("Login", login),
        ("Activated at", event_time),
        ("Source", "Okta event hook → AWS Lambda"),
        ("Status", "Account active — full identity-layer access live"),
    ]
    if dry_run:
        return {"skipped": False, "dry_run": True, "channel_name": channel_name, "text": text}
    if bot_session is None:
        return {"skipped": True, "reason": "no_bot_token"}
    try:
        channel_id = ensure_channel(bot_session, channel_name)
        ts = _post_block(bot_session, channel_id, text, fields)
    except SlackAPIError as e:
        return {"skipped": True, "reason": e.error}
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text}


def post_leaver_deactivated(
    bot_session, full_name: str, login: str, department: str, manager_email: str,
    *, dry_run: bool = False, channel_name: str = LEAVER_CHANNEL,
) -> dict:
    """Post to #leaver-it-ops when the Okta account is deactivated."""
    text = f":no_entry: *Leaver Okta account deactivated:* {full_name} ({login})"
    fields = [
        ("Department", department),
        ("Manager", manager_email or "(unset)"),
        ("Login", login),
        ("Status", "DEPROVISIONED — sessions revoked, SCIM cascade fired to Slack"),
    ]
    if dry_run:
        return {"skipped": False, "dry_run": True, "channel_name": channel_name, "text": text}
    if bot_session is None:
        return {"skipped": True, "reason": "no_bot_token"}
    try:
        channel_id = ensure_channel(bot_session, channel_name)
        ts = _post_block(bot_session, channel_id, text, fields)
    except SlackAPIError as e:
        return {"skipped": True, "reason": e.error}
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text}


def _build_batch_summary_blocks(
    run_date: str,
    activated: list[dict],
    errors: list[dict],
    skipped: list[dict] | None = None,
    batch_run_id: str = "",
) -> tuple[str, list]:
    """Block Kit payload for the daily onboarding batch summary.

    DUPLICATED IN: lambdas/onboarding_workflow/handler.py:_build_batch_summary_blocks
    Keep the two in sync — the Lambda can't import this module cleanly.
    """
    n_act = len(activated)
    n_err = len(errors)
    text = f":rocket: Daily joiner activations — {run_date}: {n_act} activated, {n_err} errors"

    blocks: list[dict] = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"🚀 Daily joiner activations — {run_date}"},
        }
    ]

    if activated:
        lines = [
            f"• {u.get('first_name', '')} {u.get('last_name', '')}".strip()
            + (f" — {u['role_title']}, {u['department']}" if u.get("role_title") or u.get("department") else "")
            + f" ({u.get('login', '')})"
            for u in activated
        ]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Activated ({n_act}):*\n" + "\n".join(lines)},
        })
    else:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Activated (0):*\n_No STAGED users with today's startDate._"},
        })

    if errors:
        err_lines = [f"• `{e.get('login', '?')}` — {e.get('error', '?')}" for e in errors]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Errors ({n_err}):*\n" + "\n".join(err_lines)},
        })

    if skipped:
        skip_lines = [f"• `{s.get('login', '?')}` — {s.get('reason', '?')}" for s in skipped]
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Skipped ({len(skipped)}):*\n" + "\n".join(skip_lines)},
        })

    blocks.append({
        "type": "context",
        "elements": [
            {"type": "mrkdwn", "text": f"batch_run_id: `{batch_run_id}` • run_date_pt: `{run_date}` • Posted by NovaTech IT Ops automation"},
        ],
    })
    return text, blocks


def post_joiner_batch_summary(
    bot_session,
    run_date: str,
    activated: list[dict],
    errors: list[dict],
    *,
    skipped: list[dict] | None = None,
    batch_run_id: str = "",
    dry_run: bool = False,
    channel_name: str = JOINER_CHANNEL,
) -> dict:
    """Post the daily onboarding-batch summary to #joiner-it-ops.

    Mirrors the Lambda's _build_batch_summary_blocks payload so the CLI
    smoke test exercises the exact same Block Kit shape that the Lambda
    will produce in production.

    `activated` entries: {"login", "first_name", "last_name", "department",
    "role_title", "user_id"} (any missing key defaults to "").
    `errors` entries: {"login", "error"}.
    """
    text, blocks = _build_batch_summary_blocks(run_date, activated, errors, skipped, batch_run_id)
    if dry_run:
        return {"skipped": False, "dry_run": True, "channel_name": channel_name, "text": text, "blocks": blocks}
    if bot_session is None:
        return {"skipped": True, "reason": "no_bot_token"}
    try:
        channel_id = ensure_channel(bot_session, channel_name)
        ts = post_message(bot_session, channel_id, text, blocks=blocks)
    except SlackAPIError as e:
        return {"skipped": True, "reason": e.error}
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text}


# --------------------------------------------------------------------------
# CLI smoke test
# --------------------------------------------------------------------------
# Run directly to exercise both channels end-to-end against the real bot:
#   python scripts/slack/notify.py
#
# Verifies channels:write, chat:write, and the Block Kit payload all work
# before joiner/leaver wire it up.
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    import sys

    bot = bot_session_if_configured()
    if bot is None:
        print("ERROR: SLACK_BOT_TOKEN not set; cannot smoke-test notify.py")
        sys.exit(1)

    print("Smoke test 1/3: post_joiner_welcome_sent → #joiner-it-ops")
    r = post_joiner_welcome_sent(
        bot, "Smoke Test Joiner", "smoke.test@ohmgym.com",
        "Engineering", "Smoke Tester",
    )
    print(json.dumps(r, indent=2))
    print()

    print("Smoke test 2/3: post_joiner_activated → #joiner-it-ops")
    r = post_joiner_activated(
        bot, "Smoke Test Joiner", "smoke.test@ohmgym.com",
        "2026-04-29T19:00:00Z",
    )
    print(json.dumps(r, indent=2))
    print()

    print("Smoke test 3/4: post_leaver_deactivated → #leaver-it-ops")
    r = post_leaver_deactivated(
        bot, "Smoke Test Leaver", "smoke.leaver@ohmgym.com",
        "Engineering", "manager@ohmgym.com",
    )
    print(json.dumps(r, indent=2))
    print()

    print("Smoke test 4/4: post_joiner_batch_summary → #joiner-it-ops")
    import uuid
    r = post_joiner_batch_summary(
        bot,
        run_date="2026-05-14",
        activated=[
            {
                "user_id": "00usmoke1",
                "login": "smoke.priya@ohmgym.com",
                "first_name": "Smoke",
                "last_name": "Priya",
                "department": "Data",
                "role_title": "Data Engineer",
            },
            {
                "user_id": "00usmoke2",
                "login": "smoke.marcus@ohmgym.com",
                "first_name": "Smoke",
                "last_name": "Marcus",
                "department": "Data",
                "role_title": "Data Analyst",
            },
        ],
        errors=[
            {"login": "smoke.error@ohmgym.com", "error": "E0000001: Bad request"},
        ],
        batch_run_id=uuid.uuid4().hex,
    )
    print(json.dumps(r, indent=2))
