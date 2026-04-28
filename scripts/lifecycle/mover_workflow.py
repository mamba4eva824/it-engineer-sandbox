#!/usr/bin/env python3
"""Mover workflow: department change -> Okta + GWS + Slack reconciliation.

When a user transfers between departments, five things must happen:

  1. Okta user.profile.department is updated (the source of truth).
  2. The existing 10 group rules (see config/okta/desired-state.json) auto-
     remove the user from the old department's OKTA_GROUP and add them to
     the new one. Because both GWS and Slack apps have SCIM GROUP_PUSH
     enabled, that membership change propagates to the Slack IdP group
     (which drives channel auto-assignment) with no extra code.
  3. GWS orgUnitPath is moved to the new department's OU via Directory API
     (Okta's GWS provisioning doesn't manage OU placement directly in this
     tenant, so we do it here — same pattern as scripts/lifecycle/sync_auth0_gws.py).
  4. A Slack DM goes to the new manager announcing the transfer.
  5. A Slack post goes to #it-ops-audit for the compliance trail.

Trigger is CLI. In a production tenant this would be wired to an Okta Event
Hook + Lambda; here the CLI is the interview-demoable equivalent of the same
orchestration code, just without a webhook receiver.

Every run appends a JSON line to logs/mover-events.jsonl so the audit trail
survives across invocations.

Usage:
  # Dry run — print the plan, call nothing that writes
  python scripts/lifecycle/mover_workflow.py \\
      --user sarah.chen@ohmgym.com --new-department Product --dry-run

  # Real run
  python scripts/lifecycle/mover_workflow.py \\
      --user sarah.chen@ohmgym.com --new-department Product

  # Skip a platform if it's having an incident (partial Mover)
  python scripts/lifecycle/mover_workflow.py \\
      --user sarah.chen@ohmgym.com --new-department Product --skip-slack
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Both scripts/okta/_client.py and scripts/slack/_client.py share the module
# name `_client`. Python caches the first import, so naively putting both on
# sys.path collides. Load each one via importlib under a distinct module name
# so we get two independent modules.

import importlib.util  # noqa: E402


def _load(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    # Scripts sit next to their _client; ensure their dir is importable so
    # sibling `from _client import ...` resolves (needed by _post.py).
    sys.path.insert(0, str(file_path.parent))
    spec.loader.exec_module(module)
    return module


okta_client = _load("okta_client", REPO_ROOT / "scripts" / "okta" / "_client.py")
# Load slack _client FIRST so that _post.py (which does `from _client import ...`)
# resolves against the slack dir on sys.path.
slack_client = _load("slack_client", REPO_ROOT / "scripts" / "slack" / "_client.py")
# _post.py does `from _client import SlackAPIError, api_url` — when we import
# it, that bare `_client` lookup will hit the slack dir that's now first on
# sys.path (because we inserted it last).
slack_post = _load("slack_post", REPO_ROOT / "scripts" / "slack" / "_post.py")

load_dotenv(REPO_ROOT / ".env")

VALID_DEPARTMENTS = {
    "Engineering", "IT-Ops", "Finance", "Executive", "Data",
    "Product", "Design", "HR", "Sales", "Marketing",
}

DEPARTMENT_TO_OU = {d: f"/{d}" for d in VALID_DEPARTMENTS}

AUDIT_CHANNEL_NAME = os.getenv("SLACK_AUDIT_CHANNEL", "it-ops-audit")
# If the xoxp token lacks conversations.list/admin.conversations.search scope
# (common on narrowly-scoped admin tokens), set SLACK_AUDIT_CHANNEL_ID to a
# known channel id like C0123456789 to skip resolve and post directly.
AUDIT_CHANNEL_ID = os.getenv("SLACK_AUDIT_CHANNEL_ID", "").strip()
AUDIT_LOG = REPO_ROOT / "logs" / "mover-events.jsonl"
GROUP_RULE_WAIT_SECS = int(os.getenv("MOVER_GROUP_RULE_WAIT", "45"))


# --------------------------------------------------------------------------
# Okta
# --------------------------------------------------------------------------

def okta_find_user(session, email: str) -> dict:
    """Look up an Okta user by login. Returns the full user object or exits."""
    resp = session.get(
        okta_client.api_url("/api/v1/users"),
        params={"search": f'profile.login eq "{email}"', "limit": 1},
        timeout=15,
    )
    resp.raise_for_status()
    hits = resp.json()
    if not hits:
        print(f"ERROR: Okta user not found: {email}")
        sys.exit(2)
    return hits[0]


def okta_update_department(session, user_id: str, new_department: str, dry_run: bool) -> None:
    """POST a profile patch that sets department. Group rules handle the rest."""
    if dry_run:
        print(f"  [DRY RUN] Would POST /api/v1/users/{user_id} with profile.department={new_department!r}")
        return
    resp = session.post(
        okta_client.api_url(f"/api/v1/users/{user_id}"),
        json={"profile": {"department": new_department}},
        timeout=15,
    )
    if resp.status_code >= 300:
        print(f"  FAILED Okta profile update: HTTP {resp.status_code} {resp.text[:300]}")
        sys.exit(3)
    print(f"  Okta profile updated: department={new_department}")


def okta_group_memberships(session, user_id: str) -> list[str]:
    """Return the names of OKTA_GROUPs the user currently belongs to."""
    resp = session.get(okta_client.api_url(f"/api/v1/users/{user_id}/groups"), timeout=15)
    resp.raise_for_status()
    return [
        g["profile"]["name"]
        for g in resp.json()
        if g.get("type") == "OKTA_GROUP"
    ]


def okta_wait_for_group_change(
    session, user_id: str, old_dept: str, new_dept: str, timeout_secs: int
) -> bool:
    """Poll until the user has left old_dept group and joined new_dept group.

    Group rule reassignment is eventually-consistent; typically within ~30s.
    Returns True if both conditions met before timeout, False otherwise.
    """
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        groups = set(okta_group_memberships(session, user_id))
        if new_dept in groups and old_dept not in groups:
            return True
        time.sleep(5)
    return False


# --------------------------------------------------------------------------
# GWS
# --------------------------------------------------------------------------

def gws_service():
    key_path = REPO_ROOT / os.environ["GWS_SERVICE_ACCOUNT_KEY"]
    admin = os.environ["GWS_ADMIN_EMAIL"]
    creds = service_account.Credentials.from_service_account_file(
        str(key_path),
        scopes=["https://www.googleapis.com/auth/admin.directory.user"],
        subject=admin,
    )
    return build("admin", "directory_v1", credentials=creds)


def gws_move_user(service, email: str, new_department: str, dry_run: bool) -> str:
    """Move the user's GWS account to /<new_department>. Returns the new OU path."""
    target_ou = DEPARTMENT_TO_OU[new_department]
    if dry_run:
        print(f"  [DRY RUN] Would update GWS user {email} orgUnitPath -> {target_ou}")
        return target_ou
    try:
        service.users().update(
            userKey=email,
            body={"orgUnitPath": target_ou},
        ).execute()
    except HttpError as e:
        print(f"  FAILED GWS OU move for {email}: {e}")
        sys.exit(4)
    print(f"  GWS user moved to OU: {target_ou}")
    return target_ou


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------

def slack_notify_manager(
    session, manager_email: str, user_name: str, old_dept: str, new_dept: str, dry_run: bool
) -> dict:
    """DM the new manager. Gracefully handles the case where manager_email isn't a Slack user."""
    text = (
        f"{user_name} just joined your team from {old_dept}. "
        f"Their access has been updated."
    )
    if dry_run:
        print(f"  [DRY RUN] Would DM {manager_email}: {text!r}")
        return {"skipped": False, "dry_run": True, "text": text}
    try:
        slack_user_id = slack_post.lookup_user_id_by_email(session, manager_email)
        channel_id = slack_post.open_dm_channel(session, slack_user_id)
        ts = slack_post.post_message(session, channel_id, text)
    except slack_post.SlackAPIError as e:
        print(f"  WARN: manager DM skipped for {manager_email} (Slack error: {e.error})")
        return {"skipped": True, "reason": e.error}
    print(f"  Slack DM to {manager_email} sent (channel={channel_id}, ts={ts})")
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text}


def slack_post_audit(
    session, user_name: str, old_dept: str, new_dept: str, dry_run: bool,
    bot_session=None,
) -> dict:
    """Post the Mover event to #it-ops-audit."""
    text = f"Mover event: {user_name}, {old_dept} → {new_dept}"
    if dry_run:
        print(f"  [DRY RUN] Would post to #{AUDIT_CHANNEL_NAME}: {text!r}")
        return {"skipped": False, "dry_run": True, "text": text}
    # Resolve channel id with the user/admin session (admin.conversations.search)
    # then post with the bot session when available. The bot token is installed
    # to the workspace that owns #it-ops-audit, which the user token isn't.
    post_session = bot_session if bot_session is not None else session
    try:
        if AUDIT_CHANNEL_ID:
            channel_id = AUDIT_CHANNEL_ID
        else:
            channel_id = slack_post.resolve_channel_id(session, AUDIT_CHANNEL_NAME)
        ts = slack_post.post_message(post_session, channel_id, text)
    except slack_post.SlackAPIError as e:
        print(f"  WARN: #{AUDIT_CHANNEL_NAME} post skipped (Slack error: {e.error})")
        return {"skipped": True, "reason": e.error}
    poster = "bot" if bot_session is not None else "user"
    print(f"  Slack audit post to #{AUDIT_CHANNEL_NAME} sent via {poster} token (channel={channel_id}, ts={ts})")
    return {"skipped": False, "channel": channel_id, "ts": ts, "text": text, "poster": poster}


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------

def append_audit(event: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps(event) + "\n")


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Run the Mover workflow for a single user.")
    parser.add_argument("--user", required=True, help="User's email/login (e.g., sarah.chen@ohmgym.com)")
    parser.add_argument("--new-department", required=True, help=f"One of: {sorted(VALID_DEPARTMENTS)}")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; make no writes.")
    parser.add_argument("--skip-gws", action="store_true", help="Skip the GWS OU move step.")
    parser.add_argument("--skip-slack", action="store_true", help="Skip the Slack DM + audit post.")
    parser.add_argument(
        "--group-rule-wait",
        type=int,
        default=GROUP_RULE_WAIT_SECS,
        help=f"Seconds to wait for Okta group rule reassignment (default: {GROUP_RULE_WAIT_SECS}).",
    )
    args = parser.parse_args()

    if args.new_department not in VALID_DEPARTMENTS:
        print(f"ERROR: --new-department must be one of {sorted(VALID_DEPARTMENTS)}")
        sys.exit(1)

    started = datetime.now(timezone.utc).isoformat()
    print(f"Mover workflow — user={args.user}  new_department={args.new_department}")
    if args.dry_run:
        print("*** DRY RUN — no writes will be performed ***")
    print()

    # --- Okta: find user, capture before-state ----------------------------
    print("Step 1: Okta — look up user and update department")
    okta_session, _ = okta_client.get_session()
    user = okta_find_user(okta_session, args.user)
    user_id = user["id"]
    profile = user.get("profile", {})
    old_department = profile.get("department", "UNKNOWN")
    manager_email = profile.get("managerEmail", "")
    full_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or args.user

    if old_department == args.new_department:
        print(f"  No-op: user is already in {args.new_department}. Exiting.")
        sys.exit(0)
    if old_department not in VALID_DEPARTMENTS:
        print(f"  WARN: old department {old_department!r} isn't in the known set; "
              f"group-rule wait step will be best-effort.")

    print(f"  Okta user: {full_name}  id={user_id}")
    print(f"  Transition: {old_department} -> {args.new_department}")
    print(f"  New manager email (from profile.managerEmail): {manager_email or '(unset)'}")
    okta_update_department(okta_session, user_id, args.new_department, args.dry_run)
    print()

    # --- Okta: wait for group rules to repropagate ------------------------
    print("Step 2: Okta group rules — wait for membership reassignment (propagates to Slack via SCIM)")
    if args.dry_run:
        print(f"  [DRY RUN] Would poll /users/{user_id}/groups until {args.new_department} present "
              f"and {old_department} absent, up to {args.group_rule_wait}s")
        group_reassigned = None
    elif old_department not in VALID_DEPARTMENTS:
        print(f"  Skipping poll: old department {old_department!r} unknown. "
              f"Verify manually via `mcp__okta__list_group_users`.")
        group_reassigned = None
    else:
        ok = okta_wait_for_group_change(
            okta_session, user_id, old_department, args.new_department, args.group_rule_wait
        )
        group_reassigned = ok
        if ok:
            print(f"  Group rule reassignment confirmed within {args.group_rule_wait}s.")
        else:
            print(f"  WARN: group reassignment not confirmed within {args.group_rule_wait}s. "
                  f"Proceeding anyway; SCIM push to Slack should still happen eventually.")
    print()

    # --- GWS: OU move -----------------------------------------------------
    print("Step 3: GWS — move user to new department OU")
    new_ou = None
    if args.skip_gws:
        print("  Skipped (--skip-gws).")
    else:
        gws = None if args.dry_run else gws_service()
        new_ou = gws_move_user(gws, args.user, args.new_department, args.dry_run)
    print()

    # --- Slack: DM manager + audit post -----------------------------------
    dm_result = {"skipped": True, "reason": "--skip-slack"}
    audit_result = {"skipped": True, "reason": "--skip-slack"}
    if args.skip_slack:
        print("Step 4 & 5: Slack notifications — skipped (--skip-slack).")
    else:
        slack_session = slack_client.get_session()
        print("Step 4: Slack — DM the new manager")
        if manager_email:
            dm_result = slack_notify_manager(
                slack_session, manager_email, full_name, old_department, args.new_department, args.dry_run
            )
        else:
            print(f"  Skipped: profile.managerEmail is empty for {args.user}.")
            dm_result = {"skipped": True, "reason": "managerEmail_unset"}
        print()

        print(f"Step 5: Slack — post to #{AUDIT_CHANNEL_NAME}")
        bot_session = slack_post.bot_session_if_configured()
        if bot_session is not None:
            print("  Using SLACK_BOT_TOKEN for audit post (workspace-scoped identity).")
        audit_result = slack_post_audit(
            slack_session, full_name, old_department, args.new_department, args.dry_run,
            bot_session=bot_session,
        )
    print()

    # --- Audit log --------------------------------------------------------
    event = {
        "event": "mover",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "user": {
            "email": args.user,
            "okta_id": user_id,
            "name": full_name,
            "manager_email": manager_email,
        },
        "transition": {"from": old_department, "to": args.new_department},
        "steps": {
            "okta_profile_updated": not args.dry_run,
            "okta_group_reassigned": group_reassigned,
            "gws_new_ou": new_ou,
            "slack_manager_dm": dm_result,
            "slack_audit_post": audit_result,
        },
    }
    if not args.dry_run:
        append_audit(event)
        print(f"Audit event appended: {AUDIT_LOG.relative_to(REPO_ROOT)}")
    else:
        print("[DRY RUN] Would append this audit event:")
        print(json.dumps(event, indent=2))

    print()
    print("=" * 60)
    print("MOVER WORKFLOW COMPLETE")
    print(f"  User: {full_name} ({args.user})")
    print(f"  {old_department} -> {args.new_department}")
    print("=" * 60)


if __name__ == "__main__":
    main()
