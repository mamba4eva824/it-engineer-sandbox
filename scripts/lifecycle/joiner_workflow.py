#!/usr/bin/env python3
"""Joiner workflow: onboard a single user across Okta + GWS alias + Slack audit.

When a new hire starts, three things must happen:

  1. An Okta user is created with the right department/role/manager profile so
     the 10 group rules (see config/okta/desired-state.json) auto-assign them
     to the correct OKTA_GROUP within ~30s. SCIM GROUP_PUSH then propagates the
     membership to Slack and (where wired) GWS, driving app access.
  2. (Sandbox-only) Because we have a single GWS license cap on chris@ohmgym.com,
     we add the new hire's login as a Gmail "+" alias on chris@. That lets any
     Okta activation/welcome mail land in chris's inbox so we can incognito-test
     the Okta dashboard sign-in. Note: GWS aliases CANNOT SAML-sign-in to Google
     independently — Google ignores the alias for IdP login. This step is purely
     for routing activation mail.
  3. A Slack post goes to #it-ops-audit for the compliance trail.

Trigger is CLI. In a production tenant this would be wired to an HRIS webhook
or SCIM-IM pull; here the CLI is the interview-demoable equivalent of the same
orchestration code, just without a webhook receiver.

Every run appends a JSON line to logs/joiner-events.jsonl so the audit trail
survives across invocations.

Usage:
  # Dry run — print the plan, call nothing that writes
  python scripts/lifecycle/joiner_workflow.py \\
      --first-name Jamie --last-name Rivera \\
      --department Engineering --role-title "Software Engineer" \\
      --cost-center ENG-100 --manager-email james.smith@ohmgym.com \\
      --start-date 2026-05-01 --email chris+jamie@ohmgym.com --dry-run

  # Real run with Gmail alias for incognito sign-in test
  python scripts/lifecycle/joiner_workflow.py \\
      --first-name Jamie --last-name Rivera \\
      --department Engineering --role-title "Software Engineer" \\
      --cost-center ENG-100 --manager-email james.smith@ohmgym.com \\
      --start-date 2026-05-01 --email chris+jamie@ohmgym.com

  # Skip GWS (no alias creation) — useful when --email is a real domain user
  python scripts/lifecycle/joiner_workflow.py ... --skip-gws-alias
"""

import argparse
import importlib.util
import json
import os
import re
import sys
import time
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
    name `_client`. Python caches the first import, so naively putting both on
    sys.path collides. Load each via importlib under a distinct module name.
    """
    spec = importlib.util.spec_from_file_location(mod_name, file_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    sys.path.insert(0, str(file_path.parent))
    spec.loader.exec_module(module)
    return module


okta_client = _load("okta_client", REPO_ROOT / "scripts" / "okta" / "_client.py")
okta_provision = _load("okta_provision", REPO_ROOT / "scripts" / "okta" / "provision_users.py")
# provision_users.py did `from _client import ...` while the okta dir was first
# on sys.path, caching `_client` as the okta one. The slack modules below also
# do `from _client import ...` and need it to resolve against scripts/slack/.
# Clear the cached bare `_client` so the next bare import resolves fresh.
sys.modules.pop("_client", None)
slack_client = _load("slack_client", REPO_ROOT / "scripts" / "slack" / "_client.py")
slack_post = _load("slack_post", REPO_ROOT / "scripts" / "slack" / "_post.py")

load_dotenv(REPO_ROOT / ".env")

VALID_DEPARTMENTS = {
    "Engineering", "IT-Ops", "Finance", "Executive", "Data",
    "Product", "Design", "HR", "Sales", "Marketing",
}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

AUDIT_CHANNEL_NAME = os.getenv("SLACK_AUDIT_CHANNEL", "it-ops-audit")
AUDIT_CHANNEL_ID = os.getenv("SLACK_AUDIT_CHANNEL_ID", "").strip()
AUDIT_LOG = REPO_ROOT / "logs" / "joiner-events.jsonl"
GROUP_RULE_WAIT_SECS = int(os.getenv("JOINER_GROUP_RULE_WAIT", "45"))
DEFAULT_ALIAS_TARGET = os.getenv("JOINER_ALIAS_TARGET", "chris@ohmgym.com")
DEFAULT_DOMAIN = "ohmgym.com"


# --------------------------------------------------------------------------
# Okta
# --------------------------------------------------------------------------

def okta_wait_for_group_join(
    session, user_id: str, dept: str, timeout_secs: int
) -> bool:
    """Poll until the user appears in the dept OKTA_GROUP (eventually-consistent)."""
    deadline = time.time() + timeout_secs
    while time.time() < deadline:
        resp = session.get(okta_client.api_url(f"/api/v1/users/{user_id}/groups"), timeout=15)
        resp.raise_for_status()
        names = {
            g["profile"]["name"]
            for g in resp.json()
            if g.get("type") == "OKTA_GROUP"
        }
        if dept in names:
            return True
        time.sleep(5)
    return False


# --------------------------------------------------------------------------
# GWS alias
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


def gws_add_alias(service, alias_target: str, alias_login: str, dry_run: bool) -> str:
    """Add `alias_login` as an alias on `alias_target` GWS user.

    Returns one of: "added", "already_exists", "skipped" (dry run).
    Idempotent: 409 (alias exists) is treated as success.
    """
    if dry_run:
        print(f"  [DRY RUN] Would add {alias_login} as alias on {alias_target}")
        return "skipped"
    try:
        service.users().aliases().insert(
            userKey=alias_target,
            body={"alias": alias_login},
        ).execute()
    except HttpError as e:
        if e.resp.status in (409, 412) or "duplicate" in str(e).lower():
            print(f"  GWS alias already exists: {alias_login} on {alias_target}")
            return "already_exists"
        print(f"  FAILED GWS alias add for {alias_login} on {alias_target}: {e}")
        sys.exit(4)
    print(f"  GWS alias added: {alias_login} -> {alias_target}")
    return "added"


# --------------------------------------------------------------------------
# Slack
# --------------------------------------------------------------------------

def slack_post_audit(
    session, full_name: str, department: str, role_title: str, login: str, dry_run: bool,
    bot_session=None,
) -> dict:
    """Post the Joiner event to #it-ops-audit."""
    text = (
        f"Joiner event: {full_name}, {department}, role={role_title}, login={login}"
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
# Helpers
# --------------------------------------------------------------------------

def derive_default_email(first: str, last: str) -> str:
    return f"{first.strip().lower()}.{last.strip().lower()}@{DEFAULT_DOMAIN}"


def has_plus_subaddress(email: str) -> bool:
    local = email.split("@", 1)[0]
    return "+" in local


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run the Joiner workflow for a single new hire.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--department", required=True, help=f"One of: {sorted(VALID_DEPARTMENTS)}")
    parser.add_argument("--role-title", required=True)
    parser.add_argument("--cost-center", required=True, help="e.g. ENG-100")
    parser.add_argument("--manager-email", required=True)
    parser.add_argument("--start-date", required=True, help="YYYY-MM-DD")
    parser.add_argument(
        "--email",
        help=f"Login. Default: <first>.<last>@{DEFAULT_DOMAIN}. "
        f"Use chris+<tag>@{DEFAULT_DOMAIN} to route activation mail to chris's inbox.",
    )
    parser.add_argument(
        "--gws-alias-on",
        default=DEFAULT_ALIAS_TARGET,
        help=f"GWS user to attach the alias to (default: {DEFAULT_ALIAS_TARGET}). "
        "Only used if --email contains a '+' subaddress.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan; make no writes.")
    parser.add_argument("--skip-gws-alias", action="store_true", help="Skip the GWS alias step.")
    parser.add_argument("--skip-slack", action="store_true", help="Skip the #it-ops-audit post.")
    parser.add_argument(
        "--group-rule-wait",
        type=int,
        default=GROUP_RULE_WAIT_SECS,
        help=f"Seconds to wait for Okta group rule assignment (default: {GROUP_RULE_WAIT_SECS}).",
    )
    args = parser.parse_args()

    if args.department not in VALID_DEPARTMENTS:
        print(f"ERROR: --department must be one of {sorted(VALID_DEPARTMENTS)}")
        sys.exit(1)
    if not DATE_RE.match(args.start_date):
        print(f"ERROR: --start-date must be YYYY-MM-DD, got {args.start_date!r}")
        sys.exit(1)
    if not EMAIL_RE.match(args.manager_email):
        print(f"ERROR: --manager-email looks malformed: {args.manager_email!r}")
        sys.exit(1)

    login = args.email or derive_default_email(args.first_name, args.last_name)
    if not EMAIL_RE.match(login):
        print(f"ERROR: derived/provided --email looks malformed: {login!r}")
        sys.exit(1)

    full_name = f"{args.first_name} {args.last_name}"
    started = datetime.now(timezone.utc).isoformat()

    print(f"Joiner workflow — name={full_name}  login={login}  dept={args.department}")
    if args.dry_run:
        print("*** DRY RUN — no writes will be performed ***")
    print()

    # --- Step 1: build profile -------------------------------------------
    print("Step 1: Build Okta profile from CLI args")
    auth0_shape = {
        "email": login,
        "given_name": args.first_name,
        "family_name": args.last_name,
        "user_metadata": {
            "department": args.department,
            "role_title": args.role_title,
            "cost_center": args.cost_center,
            "manager_email": args.manager_email,
            "start_date": args.start_date,
        },
    }
    profile = okta_provision.build_profile(auth0_shape)
    print(f"  login: {profile['login']}")
    print(f"  name: {profile['firstName']} {profile['lastName']}")
    print(f"  department: {profile['department']}  costCenter: {profile['costCenter']}")
    print(f"  role_title: {profile['role_title']}  managerEmail: {profile['managerEmail']}")
    print(f"  startDate: {profile['startDate']}")
    print()

    # --- Step 2: pre-flight existence check ------------------------------
    print("Step 2: Okta — pre-flight existence check")
    okta_session = None
    if args.dry_run:
        print(f"  [DRY RUN] Would search for profile.login eq {login!r}")
        existing_id = None
    else:
        okta_session, _ = okta_client.get_session()
        existing_id = okta_provision.user_exists(okta_session, login)
        if existing_id:
            print(f"  User already onboarded: {login}  id={existing_id}")
            print("  Exiting; no further steps run (idempotent no-op).")
            sys.exit(0)
        print(f"  No existing user with login={login}; proceeding to create.")
    print()

    # --- Step 3: create user ---------------------------------------------
    print("Step 3: Okta — create user")
    user_id = ""
    password = ""
    okta_user_created = False
    if args.dry_run:
        redacted = {"profile": profile, "credentials": {"password": {"value": "<redacted>"}}}
        print(f"  [DRY RUN] Would POST /api/v1/users?activate=true:")
        print(f"  {json.dumps(redacted, indent=2)}")
    else:
        password = okta_provision.generate_password()
        status, detail = okta_provision.create_user(okta_session, profile, password)
        if status == "created":
            user_id = detail
            okta_user_created = True
            print(f"  Created: {login}  id={user_id}")
        elif status == "exists":
            print(f"  Skipped (race): {login} — user appeared between pre-flight and POST.")
        else:
            print(f"  FAILED: {detail}")
            sys.exit(3)
    print()

    # --- Step 4: wait for group rule -------------------------------------
    print(f"Step 4: Okta group rule — wait for {args.department} membership")
    group_assigned = None
    if args.dry_run:
        print(f"  [DRY RUN] Would poll /users/<id>/groups until {args.department} present, "
              f"up to {args.group_rule_wait}s")
    elif user_id:
        ok = okta_wait_for_group_join(
            okta_session, user_id, args.department, args.group_rule_wait
        )
        group_assigned = ok
        if ok:
            print(f"  Group rule fired: user is in {args.department} within {args.group_rule_wait}s.")
        else:
            print(f"  WARN: {args.department} membership not confirmed within {args.group_rule_wait}s. "
                  "Group rules are eventually-consistent; check Okta admin if persistent.")
    else:
        print("  Skipped: no user id (creation race or skipped).")
    print()

    # --- Step 5: GWS alias ------------------------------------------------
    print("Step 5: GWS — add Gmail '+' alias for incognito sign-in test")
    alias_result = "skipped"
    if args.skip_gws_alias:
        print("  Skipped (--skip-gws-alias).")
    elif not has_plus_subaddress(login):
        print(f"  Skipped: login {login} has no '+' subaddress; no alias needed.")
    else:
        gws = None if args.dry_run else gws_service()
        alias_result = gws_add_alias(gws, args.gws_alias_on, login, args.dry_run)
    print()

    # --- Step 6: Slack audit post ----------------------------------------
    print(f"Step 6: Slack — post to #{AUDIT_CHANNEL_NAME}")
    audit_result = {"skipped": True, "reason": "--skip-slack"}
    if args.skip_slack:
        print("  Skipped (--skip-slack).")
    else:
        if args.dry_run:
            audit_result = slack_post_audit(
                None, full_name, args.department, args.role_title, login, dry_run=True,
            )
        else:
            slack_session = slack_client.get_session()
            bot_session = slack_post.bot_session_if_configured()
            if bot_session is not None:
                print("  Using SLACK_BOT_TOKEN for audit post (workspace-scoped identity).")
            audit_result = slack_post_audit(
                slack_session, full_name, args.department, args.role_title, login,
                dry_run=False, bot_session=bot_session,
            )
    print()

    # --- Step 7: persist credentials -------------------------------------
    creds_path = None
    if not args.dry_run and password and user_id:
        LOGS_DIR = REPO_ROOT / "logs"
        LOGS_DIR.mkdir(exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        creds_path = LOGS_DIR / f"joiner-credentials-{ts}.json"
        with open(creds_path, "w") as f:
            json.dump([{
                "email": login,
                "okta_user_id": user_id,
                "password": password,
            }], f, indent=2)
        creds_path.chmod(0o600)
        print(f"Credentials written to {creds_path.relative_to(REPO_ROOT)} (mode 600)")
        print()

    # --- Step 8: audit log ------------------------------------------------
    event = {
        "event": "joiner",
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": args.dry_run,
        "user": {
            "email": login,
            "okta_id": user_id,
            "name": full_name,
            "department": args.department,
            "role_title": args.role_title,
            "manager_email": args.manager_email,
            "start_date": args.start_date,
        },
        "steps": {
            "okta_user_created": okta_user_created,
            "okta_group_assigned": group_assigned,
            "gws_alias_added": alias_result,
            "slack_audit_post": audit_result,
        },
    }
    if not args.dry_run:
        append_audit(event)
        print(f"Audit event appended: {AUDIT_LOG.relative_to(REPO_ROOT)}")
    else:
        print("[DRY RUN] Would append this audit event:")
        print(json.dumps(event, indent=2))

    # --- Step 9: summary --------------------------------------------------
    org_url = os.getenv("OKTA_ORG_URL", "").rstrip("/")
    print()
    print("=" * 60)
    print("JOINER WORKFLOW COMPLETE")
    print(f"  User: {full_name} ({login})")
    print(f"  Department: {args.department}  Role: {args.role_title}")
    if user_id:
        print(f"  Okta id: {user_id}")
    if alias_result == "added":
        print(f"  Activation mail will arrive at {args.gws_alias_on}'s inbox.")
    if not args.dry_run and org_url:
        print(f"  Next: open incognito → {org_url} → sign in as {login}")
    print("=" * 60)


if __name__ == "__main__":
    main()
