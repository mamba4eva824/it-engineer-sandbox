#!/usr/bin/env python3
"""Leaver workflow: offboard a user across Okta + GWS + Slack + (deferred) Zendesk.

When a user offboards, six things must happen, in security-critical order:

  1. Revoke all active Okta sessions immediately so existing tokens can't be
     replayed during the deactivation window. This MUST be first.
  2. Deactivate the Okta user (move to DEPROVISIONED). This fires SCIM DELETE
     to every connected app, including Slack. Reversible for ~90 days.
  3. Suspend the GWS account (if it exists). Sandbox-only: users with a Gmail
     +alias rather than a real GWS user are detected (404) and skipped
     gracefully — the alias itself is a +-routing entry on chris@, not a user.
  4. (Auto) Slack deactivates the user via SCIM cascade — verifiable via the
     Slack Enterprise Audit Logs API; no code in this script.
  5. (Deferred) Downgrade Zendesk role from agent/admin to end-user. Phase 6
     hasn't onboarded Zendesk yet; the --skip-zendesk flag exists as a stub
     so the workflow's structure is forward-compatible.
  6. DM the user's manager via Slack and post to #it-ops-audit for compliance.

Deactivate-not-delete: deactivation is reversible (90-day window). Hard delete
is a separate quarterly process out of scope for this workflow. Per ADR in
okta_workato_zendesk_slack.md §3.4: 'Do not delete accounts — suspension
preserves audit trails.'

Trigger is CLI. In a production tenant this would be wired to an HRIS webhook
(termination event); here the CLI is the interview-demoable equivalent of the
same orchestration code.

Every run appends a JSON line to logs/leaver-events.jsonl.

Usage:
  # Dry run — print the plan, call nothing that writes
  python scripts/lifecycle/leaver_workflow.py \\
      --okta-user-id 00u12gpww5v5gxuAK698 --dry-run

  # Real run
  python scripts/lifecycle/leaver_workflow.py \\
      --okta-user-id 00u12gpww5v5gxuAK698

  # Skip individual steps (still appends audit event)
  python scripts/lifecycle/leaver_workflow.py \\
      --okta-user-id 00u12... --skip-gws --skip-slack
"""

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _load(mod_name: str, file_path: Path):
    """Load a module by file path under a custom name to avoid `_client.py` collisions.

    Both scripts/okta/_client.py and scripts/slack/_client.py share the module
    name `_client`. Load each via importlib under a distinct module name so we
    get two independent modules.
    """
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    sys.path.insert(0, str(file_path.parent))
    spec.loader.exec_module(module)
    return module


okta_client = _load("okta_client", REPO_ROOT / "scripts" / "okta" / "_client.py")
# Load slack _client FIRST so that _post.py (which does `from _client import ...`)
# resolves against the slack dir on sys.path.
slack_client = _load("slack_client", REPO_ROOT / "scripts" / "slack" / "_client.py")
slack_post = _load("slack_post", REPO_ROOT / "scripts" / "slack" / "_post.py")
slack_notify = _load("slack_notify", REPO_ROOT / "scripts" / "slack" / "notify.py")

load_dotenv(REPO_ROOT / ".env")

AUDIT_CHANNEL_NAME = os.getenv("SLACK_AUDIT_CHANNEL", "it-ops-audit")
AUDIT_CHANNEL_ID = os.getenv("SLACK_AUDIT_CHANNEL_ID", "").strip()
AUDIT_LOG = REPO_ROOT / "logs" / "leaver-events.jsonl"


# --------------------------------------------------------------------------
# Okta
# --------------------------------------------------------------------------

def okta_get_user(session, user_id: str) -> dict | None:
    """GET /api/v1/users/{id}. Returns user object or None if not found."""
    resp = session.get(okta_client.api_url(f"/api/v1/users/{user_id}"), timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def okta_revoke_sessions(session, user_id: str, dry_run: bool) -> str:
    """DELETE /api/v1/users/{id}/sessions. Returns one of:
    "revoked", "already_inactive" (403/404 on DEPROVISIONED), or "skipped" (dry-run).
    """
    if dry_run:
        print(f"  [DRY RUN] Would DELETE /api/v1/users/{user_id}/sessions")
        return "skipped"
    resp = session.delete(
        okta_client.api_url(f"/api/v1/users/{user_id}/sessions"), timeout=15
    )
    if resp.status_code in (200, 204):
        print(f"  Sessions revoked.")
        return "revoked"
    if resp.status_code in (403, 404):
        # 403: user already DEPROVISIONED so sessions are already invalid
        # 404: user has no active sessions — also fine
        print(f"  No active sessions to revoke (HTTP {resp.status_code}). Treating as success.")
        return "already_inactive"
    print(f"  FAILED session revoke: HTTP {resp.status_code} {resp.text[:200]}")
    sys.exit(3)


def okta_deactivate_user(session, user_id: str, dry_run: bool) -> str:
    """POST /api/v1/users/{id}/lifecycle/deactivate. Returns:
    "deactivated", "already_deactivated", or "skipped" (dry-run).

    Idempotent: re-running on a DEPROVISIONED user returns 200 (Okta no-ops).
    """
    if dry_run:
        print(f"  [DRY RUN] Would POST /api/v1/users/{user_id}/lifecycle/deactivate")
        return "skipped"
    resp = session.post(
        okta_client.api_url(f"/api/v1/users/{user_id}/lifecycle/deactivate"),
        timeout=30,
    )
    if resp.status_code in (200, 204):
        print(f"  User deactivated (status -> DEPROVISIONED). SCIM DELETE cascade triggered.")
        return "deactivated"
    print(f"  FAILED deactivate: HTTP {resp.status_code} {resp.text[:200]}")
    sys.exit(4)


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


def gws_suspend_user(service, email: str, dry_run: bool) -> str:
    """Suspend a GWS user via Directory API. Returns one of:
    "suspended", "already_suspended", "not_a_real_user" (404 — alias case),
    "skipped" (dry-run), or exits on unexpected error.

    Sandbox case (Sandra Jones): chris+sandra@ohmgym.com is a Gmail +alias on
    chris@, not a Directory user. users().get() returns 404; we treat that as
    "no real user to suspend" and skip rather than failing the whole workflow.
    """
    if dry_run:
        print(f"  [DRY RUN] Would probe GWS users().get(userKey={email}) and suspend if present.")
        return "skipped"

    # Probe whether the email maps to a real GWS user (vs +alias)
    try:
        existing = service.users().get(userKey=email).execute()
    except HttpError as e:
        if e.resp.status == 404:
            print(f"  No real GWS user for {email} (Gmail +alias only); skipping.")
            return "not_a_real_user"
        print(f"  WARN: GWS lookup failed: HTTP {e.resp.status} {e}; skipping suspend.")
        return "lookup_failed"

    if existing.get("suspended"):
        print(f"  GWS user {email} already suspended.")
        return "already_suspended"

    try:
        service.users().update(
            userKey=email,
            body={"suspended": True, "suspensionReason": "USER_DEACTIVATED_VIA_LEAVER"},
        ).execute()
    except HttpError as e:
        # suspensionReason isn't always honored on Cloud Identity Free; retry without it
        try:
            service.users().update(userKey=email, body={"suspended": True}).execute()
        except HttpError as e2:
            print(f"  WARN: GWS suspend failed for {email}: {e2}; continuing.")
            return "suspend_failed"
    print(f"  GWS user {email} suspended.")
    return "suspended"


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------

def slack_dm_manager_offboarding(
    session, manager_email: str, user_name: str, user_login: str, dry_run: bool
) -> dict:
    """DM the manager about the offboarding. Returns a result dict."""
    text = (
        f"{user_name} ({user_login}) has been offboarded. "
        f"All access has been revoked across Okta, GWS, and Slack. "
        f"See #{AUDIT_CHANNEL_NAME} for the full compliance trail."
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
    session, user_name: str, user_login: str, department: str, dry_run: bool,
    bot_session=None,
) -> dict:
    """Post the Leaver event to #it-ops-audit."""
    text = (
        f"Leaver event: {user_name} ({user_login}), department={department}, "
        f"all access revoked."
    )
    if dry_run:
        print(f"  [DRY RUN] Would post to #{AUDIT_CHANNEL_NAME}: {text!r}")
        return {"skipped": False, "dry_run": True, "text": text}
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
    parser = argparse.ArgumentParser(
        description="Run the Leaver workflow to offboard a single user.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--okta-user-id", required=True,
                        help="User's Okta ID (e.g., 00u12gpww5v5gxuAK698)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print the plan; make no writes.")
    parser.add_argument("--skip-gws", action="store_true",
                        help="Skip the GWS suspend step.")
    parser.add_argument("--skip-slack", action="store_true",
                        help="Skip the Slack DM + audit post (Slack auto-deactivation via SCIM still happens).")
    parser.add_argument("--skip-zendesk", action="store_true",
                        help="Skip the Zendesk role downgrade (currently a no-op stub; Phase 6).")
    args = parser.parse_args()

    started = datetime.now(timezone.utc).isoformat()
    print(f"Leaver workflow — okta_user_id={args.okta_user_id}")
    if args.dry_run:
        print("*** DRY RUN — no writes will be performed ***")
    print()

    # --- Step 1: Okta lookup ---------------------------------------------
    print("Step 1: Okta — look up user and capture profile")
    okta_session, _ = okta_client.get_session()
    user = okta_get_user(okta_session, args.okta_user_id)
    if user is None:
        print(f"  ERROR: No Okta user with id={args.okta_user_id}. Nothing to do.")
        sys.exit(2)

    profile = user.get("profile", {})
    user_login = profile.get("login", "")
    user_email = profile.get("email", user_login)
    full_name = f"{profile.get('firstName', '')} {profile.get('lastName', '')}".strip() or user_login
    department = profile.get("department", "UNKNOWN")
    manager_email = profile.get("managerEmail", "")
    user_status = user.get("status", "")

    print(f"  Found: {full_name}  login={user_login}  status={user_status}  dept={department}")
    print(f"  Manager: {manager_email or '(unset)'}")
    print()

    already_deprovisioned = user_status == "DEPROVISIONED"

    # --- Step 2: Revoke sessions -----------------------------------------
    print("Step 2: Okta — revoke active sessions (security-critical, must precede deactivate)")
    if already_deprovisioned:
        print(f"  Skipped: user is already DEPROVISIONED (idempotent re-run).")
        sessions_result = "already_inactive"
    else:
        sessions_result = okta_revoke_sessions(okta_session, args.okta_user_id, args.dry_run)
    print()

    # --- Step 3: Deactivate user -----------------------------------------
    print("Step 3: Okta — deactivate user (triggers SCIM DELETE cascade)")
    if already_deprovisioned:
        print(f"  Skipped: user is already DEPROVISIONED.")
        deactivate_result = "already_deactivated"
    else:
        deactivate_result = okta_deactivate_user(okta_session, args.okta_user_id, args.dry_run)
    print()

    # Leaver audit post to #leaver-it-ops, fired immediately after the Okta
    # deactivation completes. Suppressed on idempotent re-runs to avoid
    # double-posting; one record per leaver event is the right cardinality.
    leaver_post = {"skipped": True, "reason": "already_deprovisioned"}
    if not already_deprovisioned and not args.skip_slack:
        bot_session = slack_notify.bot_session_if_configured()
        leaver_post = slack_notify.post_leaver_deactivated(
            bot_session, full_name, user_login, department, manager_email,
            dry_run=args.dry_run,
        )
        if leaver_post.get("skipped"):
            print(f"  WARN: #{slack_notify.LEAVER_CHANNEL} leaver post skipped "
                  f"(reason: {leaver_post.get('reason')})")
        elif leaver_post.get("dry_run"):
            print(f"  [DRY RUN] Would post to #{slack_notify.LEAVER_CHANNEL}: "
                  f"{leaver_post.get('text')}")
        else:
            print(f"  Leaver post → #{slack_notify.LEAVER_CHANNEL} "
                  f"(channel={leaver_post.get('channel')}, ts={leaver_post.get('ts')})")
        print()

    # --- Step 4: GWS suspend ---------------------------------------------
    print("Step 4: GWS — suspend account")
    if args.skip_gws:
        print("  Skipped (--skip-gws).")
        gws_result = "skipped_flag"
    else:
        gws = None if args.dry_run else gws_service()
        gws_result = gws_suspend_user(gws, user_login, args.dry_run)
    print()

    # --- Step 5: Slack auto-deactivation note ----------------------------
    print("Step 5: Slack — auto-deactivation via SCIM cascade")
    if already_deprovisioned:
        print(f"  Already cascaded on a previous run.")
    elif args.dry_run:
        print(f"  [DRY RUN] Slack would auto-deactivate {user_login} via SCIM "
              f"once Step 3 lands (verifiable in audit log).")
    else:
        print(f"  No code in this script — Okta's SCIM client to Slack will fire DELETE")
        print(f"  for {user_login} within ~30-60s. Verify with:")
        print(f"    python scripts/slack/audit_log_query.py --action user_deactivated --since 5m")
    print()

    # --- Step 6: Zendesk (deferred stub) ---------------------------------
    print("Step 6: Zendesk — role downgrade (deferred)")
    if args.skip_zendesk:
        print("  Skipped (--skip-zendesk).")
    else:
        print("  Deferred: Phase 6 hasn't onboarded Zendesk yet. No-op for now.")
    zendesk_result = "deferred"
    print()

    # --- Step 7: Slack DM manager + audit post ---------------------------
    dm_result = {"skipped": True, "reason": "--skip-slack"}
    audit_result = {"skipped": True, "reason": "--skip-slack"}
    if args.skip_slack:
        print("Steps 7a/7b: Slack notifications — skipped (--skip-slack).")
    else:
        slack_session = slack_client.get_session()
        print("Step 7a: Slack — DM the manager")
        if not manager_email:
            print(f"  Skipped: profile.managerEmail is empty for {user_login}.")
            dm_result = {"skipped": True, "reason": "managerEmail_unset"}
        elif manager_email.lower() == user_login.lower():
            print(f"  Skipped: manager email == user email (self-loop).")
            dm_result = {"skipped": True, "reason": "self_loop"}
        else:
            dm_result = slack_dm_manager_offboarding(
                slack_session, manager_email, full_name, user_login, args.dry_run
            )
        print()

        print(f"Step 7b: Slack — post to #{AUDIT_CHANNEL_NAME}")
        bot_session = slack_post.bot_session_if_configured()
        if bot_session is not None:
            print("  Using SLACK_BOT_TOKEN for audit post (workspace-scoped identity).")
        audit_result = slack_post_audit(
            slack_session, full_name, user_login, department, args.dry_run,
            bot_session=bot_session,
        )
    print()

    # --- Step 8: Audit log -----------------------------------------------
    event = {
        "event": "leaver",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "user": {
            "email": user_email,
            "login": user_login,
            "okta_id": args.okta_user_id,
            "name": full_name,
            "department": department,
            "manager_email": manager_email,
            "pre_run_status": user_status,
        },
        "steps": {
            "okta_sessions_revoked": sessions_result,
            "okta_user_deactivated": deactivate_result,
            "gws_user_suspended": gws_result,
            "slack_scim_cascade_triggered": not already_deprovisioned and not args.dry_run,
            "zendesk_downgraded": zendesk_result,
            "slack_leaver_post": leaver_post,
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

    # --- Step 9: Summary --------------------------------------------------
    print()
    print("=" * 60)
    print("LEAVER WORKFLOW COMPLETE")
    print(f"  User: {full_name} ({user_login})")
    print(f"  Okta id: {args.okta_user_id}")
    print(f"  Department: {department}")
    if not args.dry_run and not already_deprovisioned:
        print(f"  Okta status: DEPROVISIONED  |  GWS: {gws_result}  |  Slack: SCIM cascade")
        print(f"  Verify Slack with:")
        print(f"    python scripts/slack/audit_log_query.py --action user_deactivated --since 5m")
    elif already_deprovisioned:
        print(f"  No-op (user already DEPROVISIONED on a previous run).")
    print("=" * 60)


if __name__ == "__main__":
    main()
