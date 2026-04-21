#!/usr/bin/env python3
"""Export the live Okta tenant RBAC state to config/okta/desired-state.json.

Captures the three things this plan's reconcile tool manages:
  - Custom profile attributes (on the default user schema)
  - Groups (OKTA_GROUP type only; BUILT_IN and APP_GROUP are ignored)
  - Group rules (name, expression, target groups, status)

The written JSON is the source of truth for reconcile_config.py. Safety:
  - Writes to a `.tmp` file first
  - If the target already exists and differs, prints a diff summary and
    requires --force to overwrite (protects hand-edits from a routine export)

Usage:
  python scripts/okta/export_config.py
  python scripts/okta/export_config.py --pretty       # print to stdout instead
  python scripts/okta/export_config.py --force        # overwrite even if human edits present
  python scripts/okta/export_config.py --out other.json
"""

import argparse
import difflib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _client import OKTA_ORG_URL, api_url, get_session, paginate


DEFAULT_OUT = Path(__file__).parent.parent.parent / "config" / "okta" / "desired-state.json"

# Attributes we manage via config-as-code. Ignore everything else Okta adds
# to the default schema (firstName, lastName, login, etc. are built-in).
MANAGED_ATTRS = {"role_title", "managerEmail", "startDate"}


def export_profile_attributes(session) -> list[dict]:
    resp = session.get(api_url("/api/v1/meta/schemas/user/default"), timeout=30)
    resp.raise_for_status()
    schema = resp.json()
    custom = schema.get("definitions", {}).get("custom", {}).get("properties", {}) or {}
    attrs = []
    for variable_name, spec in custom.items():
        if variable_name not in MANAGED_ATTRS:
            continue
        attrs.append({
            "variableName": variable_name,
            "title": spec.get("title", variable_name),
            "type": spec.get("type", "string"),
            "required": variable_name in (schema.get("definitions", {})
                                                 .get("custom", {}).get("required", []) or []),
            "description": spec.get("description", ""),
            "enum": spec.get("enum"),
            "pattern": spec.get("pattern"),
            "permissions": spec.get("permissions", [{"principal": "SELF", "action": "READ_ONLY"}]),
        })
    attrs.sort(key=lambda a: a["variableName"])
    return attrs


def export_groups(session) -> list[dict]:
    groups = []
    for g in paginate(session, api_url("/api/v1/groups"), params={"limit": 200}):
        if g.get("type") != "OKTA_GROUP":
            continue  # skip BUILT_IN (Everyone) and APP_GROUP
        profile = g.get("profile", {})
        groups.append({
            "id": g["id"],
            "name": profile.get("name", ""),
            "description": profile.get("description", "") or "",
            "type": "OKTA_GROUP",
        })
    groups.sort(key=lambda g: g["name"])
    return groups


def export_group_rules(session, group_id_to_name: dict[str, str]) -> list[dict]:
    rules = []
    for r in paginate(session, api_url("/api/v1/groups/rules"), params={"limit": 50}):
        actions = r.get("actions", {}).get("assignUserToGroups", {})
        target_ids = actions.get("groupIds", []) or []
        rules.append({
            "name": r.get("name", ""),
            "status": r.get("status", "INACTIVE"),
            "expression": {
                "type": r.get("conditions", {}).get("expression", {}).get("type",
                                                                          "urn:okta:expression:1.0"),
                "value": r.get("conditions", {}).get("expression", {}).get("value", ""),
            },
            "assignUserToGroups": sorted(
                group_id_to_name.get(gid, gid) for gid in target_ids
            ),
        })
    rules.sort(key=lambda r: r["name"])
    return rules


def build_snapshot(session) -> dict:
    print("Exporting profile attributes...")
    attrs = export_profile_attributes(session)
    print(f"  {len(attrs)} managed attributes")

    print("Exporting groups...")
    groups = export_groups(session)
    print(f"  {len(groups)} OKTA_GROUP groups")

    print("Exporting group rules...")
    id_to_name = {g["id"]: g["name"] for g in groups}
    rules = export_group_rules(session, id_to_name)
    print(f"  {len(rules)} group rules")

    # Strip internal-only ids before writing
    for g in groups:
        g.pop("id", None)

    return {
        "schemaVersion": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "oktaDomain": OKTA_ORG_URL.replace("https://", "").replace("http://", ""),
        "profileAttributes": attrs,
        "groups": groups,
        "groupRules": rules,
    }


def _diff(existing: str, new: str) -> list[str]:
    return list(difflib.unified_diff(
        existing.splitlines(keepends=True),
        new.splitlines(keepends=True),
        fromfile="current desired-state.json",
        tofile="would-write",
        n=2,
    ))


def main():
    parser = argparse.ArgumentParser(description="Export Okta tenant RBAC state to JSON")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="Output path")
    parser.add_argument("--pretty", action="store_true",
                        help="Print JSON to stdout instead of writing to disk")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite target even if its contents differ (bypasses human-edit guard)")
    args = parser.parse_args()

    session, _ = get_session()
    print("Authenticated with Okta Management API\n")

    snapshot = build_snapshot(session)
    new_json = json.dumps(snapshot, indent=2, sort_keys=False) + "\n"

    if args.pretty:
        print(new_json)
        return

    out_path = Path(args.out)
    if out_path.exists() and not args.force:
        existing = out_path.read_text()
        # Strip the exportedAt timestamp before comparing so routine re-exports
        # don't trip the guard over a single line.
        def strip_ts(text: str) -> str:
            return "\n".join(l for l in text.splitlines() if '"exportedAt"' not in l)
        if strip_ts(existing) != strip_ts(new_json):
            print(f"\nRefusing to overwrite {out_path}: content would change.")
            print("If the change is intentional, re-run with --force.")
            print("Diff preview:\n")
            diff = _diff(existing, new_json)
            sys.stdout.writelines(diff[:60])  # cap to keep output manageable
            if len(diff) > 60:
                print(f"... ({len(diff) - 60} more diff lines truncated)")
            sys.exit(2)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(new_json)
    tmp.replace(out_path)
    print(f"\nSnapshot written: {out_path}")
    print(f"File size: {out_path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
