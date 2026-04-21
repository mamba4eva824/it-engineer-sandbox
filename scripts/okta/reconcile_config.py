#!/usr/bin/env python3
"""Reconcile the live Okta tenant against config/okta/desired-state.json.

Diffs three surfaces:
  - Profile attributes (presence, type, enum values, required flag, pattern)
  - Groups (presence, description)
  - Group rules (presence, expression, target groups, active status)

Modes:
  --audit       Report drift only (default; safe to run anywhere)
  --apply       Remediate drift (create/update; no deletion of extras)
  --dry-run     With --apply, show intended writes without making them

The remediation path is intentionally conservative: it CREATES missing objects
and UPDATES descriptions/expressions, but does NOT delete groups/rules/attrs
that exist in the tenant but are absent from desired-state. Deletion is a
two-step: remove from desired-state, run `--apply`, then delete manually.
Rationale: accidental deletions of group rules are very expensive to recover.

Usage:
  python scripts/okta/reconcile_config.py
  python scripts/okta/reconcile_config.py --apply --dry-run
  python scripts/okta/reconcile_config.py --apply
  python scripts/okta/reconcile_config.py --apply --report
  python scripts/okta/reconcile_config.py --in path/to/snapshot.json
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from _client import api_url, get_session, paginate


DEFAULT_IN = Path(__file__).parent.parent.parent / "config" / "okta" / "desired-state.json"
REPORTS_DIR = Path(__file__).parent.parent.parent / "public-docs" / "reports"

MANAGED_ATTRS = {"role_title", "managerEmail", "startDate"}


# ---------------- Load desired state ----------------

def load_desired(path: Path) -> dict:
    if not path.exists():
        print(f"ERROR: desired-state not found: {path}")
        print("Run scripts/okta/export_config.py first, or hand-write the seed file.")
        sys.exit(1)
    return json.loads(path.read_text())


# ---------------- Fetch live state ----------------

def fetch_live_schema(session) -> dict:
    resp = session.get(api_url("/api/v1/meta/schemas/user/default"), timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_live_groups(session) -> dict[str, dict]:
    groups: dict[str, dict] = {}
    for g in paginate(session, api_url("/api/v1/groups"), params={"limit": 200}):
        if g.get("type") != "OKTA_GROUP":
            continue
        profile = g.get("profile", {})
        name = profile.get("name", "")
        groups[name] = {
            "id": g["id"],
            "name": name,
            "description": profile.get("description", "") or "",
        }
    return groups


def fetch_live_rules(session, id_to_name: dict[str, str]) -> dict[str, dict]:
    rules: dict[str, dict] = {}
    for r in paginate(session, api_url("/api/v1/groups/rules"), params={"limit": 50}):
        name = r.get("name", "")
        actions = r.get("actions", {}).get("assignUserToGroups", {})
        rules[name] = {
            "id": r["id"],
            "name": name,
            "status": r.get("status", "INACTIVE"),
            "expression_value": r.get("conditions", {}).get("expression", {}).get("value", ""),
            "expression_type": r.get("conditions", {}).get("expression", {}).get(
                "type", "urn:okta:expression:1.0"),
            "target_names": sorted(
                id_to_name.get(gid, gid) for gid in actions.get("groupIds", []) or []
            ),
            "target_ids": list(actions.get("groupIds", []) or []),
        }
    return rules


# ---------------- Diff ----------------

def diff_schema(desired_attrs: list[dict], live_schema: dict) -> dict:
    live_custom = live_schema.get("definitions", {}).get("custom", {}).get("properties", {}) or {}
    live_required = set(live_schema.get("definitions", {}).get("custom", {}).get("required", []) or [])

    desired_map = {a["variableName"]: a for a in desired_attrs}
    missing = [n for n in desired_map if n not in live_custom]
    mismatched = []
    for name, d in desired_map.items():
        if name in live_custom:
            l = live_custom[name]
            if d.get("type", "string") != l.get("type", "string") \
               or d.get("enum") != l.get("enum") \
               or d.get("pattern") != l.get("pattern") \
               or bool(d.get("required", False)) != (name in live_required) \
               or (d.get("title") or name) != (l.get("title") or name):
                mismatched.append({"name": name, "desired": d, "actual_type": l.get("type"),
                                   "actual_required": name in live_required})
    extra_managed = [n for n in live_custom if n in MANAGED_ATTRS and n not in desired_map]
    return {
        "missing": missing,
        "mismatched": mismatched,
        "extra_managed": extra_managed,
        "desired_map": desired_map,
    }


def diff_groups(desired_list: list[dict], live_map: dict[str, dict]) -> dict:
    desired_map = {g["name"]: g for g in desired_list}
    missing = [n for n in desired_map if n not in live_map]
    extra = [n for n in live_map if n not in desired_map]
    description_mismatch = []
    for name, d in desired_map.items():
        if name in live_map and (d.get("description", "") or "") != (live_map[name]["description"] or ""):
            description_mismatch.append({
                "name": name,
                "desired": d.get("description", ""),
                "actual": live_map[name]["description"],
            })
    return {"missing": missing, "extra": extra,
            "description_mismatch": description_mismatch, "desired_map": desired_map}


def diff_rules(desired_list: list[dict], live_map: dict[str, dict]) -> dict:
    desired_map = {r["name"]: r for r in desired_list}
    missing = [n for n in desired_map if n not in live_map]
    extra = [n for n in live_map if n not in desired_map]
    mismatched = []
    for name, d in desired_map.items():
        if name in live_map:
            l = live_map[name]
            d_expr = d.get("expression", {}).get("value", "")
            d_targets = sorted(d.get("assignUserToGroups", []))
            if d_expr != l["expression_value"] \
               or d_targets != l["target_names"] \
               or d.get("status", "ACTIVE") != l["status"]:
                mismatched.append({"name": name, "desired": d, "actual": l})
    return {"missing": missing, "extra": extra, "mismatched": mismatched, "desired_map": desired_map}


# ---------------- Apply ----------------

def apply_schema(session, drift: dict, dry_run: bool) -> int:
    if not drift["missing"] and not drift["mismatched"]:
        return 0

    # Build the schema PATCH: include EVERY managed attribute in desired state
    # so a single POST covers all adds + updates.
    props: dict[str, dict] = {}
    required: list[str] = []
    for name, spec in drift["desired_map"].items():
        attr = {"title": spec.get("title", name),
                "type": spec.get("type", "string"),
                "permissions": spec.get("permissions",
                                        [{"principal": "SELF", "action": "READ_ONLY"}])}
        if spec.get("description"):
            attr["description"] = spec["description"]
        if spec.get("enum"):
            attr["enum"] = spec["enum"]
        if spec.get("pattern"):
            attr["pattern"] = spec["pattern"]
        props[name] = attr
        if spec.get("required"):
            required.append(name)

    body = {"definitions": {"custom": {"id": "#custom", "type": "object",
                                       "properties": props, "required": required}}}
    change_count = len(drift["missing"]) + len(drift["mismatched"])

    if dry_run:
        for n in drift["missing"]:
            print(f"  [DRY RUN] Would add schema attribute: {n}")
        for m in drift["mismatched"]:
            print(f"  [DRY RUN] Would update schema attribute: {m['name']}")
        return change_count

    resp = session.post(api_url("/api/v1/meta/schemas/user/default"),
                        json=body, timeout=30)
    if resp.status_code >= 300:
        print(f"  FAILED schema update: HTTP {resp.status_code} {resp.text}")
        return 0
    for n in drift["missing"]:
        print(f"  Added schema attribute: {n}")
    for m in drift["mismatched"]:
        print(f"  Updated schema attribute: {m['name']}")
    return change_count


def apply_groups(session, drift: dict, dry_run: bool) -> tuple[int, dict[str, str]]:
    """Returns (change_count, updated name->id map of all desired groups)."""
    changes = 0
    # Re-fetch live afterwards so caller has authoritative ids for rule remediation
    created: dict[str, str] = {}
    for name in drift["missing"]:
        spec = drift["desired_map"][name]
        if dry_run:
            print(f"  [DRY RUN] Would create group: {name}")
            changes += 1
            continue
        body = {"profile": {"name": name, "description": spec.get("description", "")}}
        resp = session.post(api_url("/api/v1/groups"), json=body, timeout=15)
        if resp.status_code >= 300:
            print(f"  FAILED create group {name}: HTTP {resp.status_code} {resp.text}")
            continue
        created[name] = resp.json()["id"]
        print(f"  Created group: {name}")
        changes += 1

    for m in drift["description_mismatch"]:
        if dry_run:
            print(f"  [DRY RUN] Would update group description: {m['name']}")
            changes += 1
            continue
        # We need the id; fetch on demand
        resp = session.get(api_url("/api/v1/groups"),
                           params={"q": m["name"], "limit": 10}, timeout=15)
        hit = next((g for g in resp.json()
                    if g.get("type") == "OKTA_GROUP"
                    and g.get("profile", {}).get("name") == m["name"]), None)
        if not hit:
            print(f"  FAILED update group {m['name']}: not found")
            continue
        body = {"profile": {"name": m["name"], "description": m["desired"]}}
        upd = session.put(api_url(f"/api/v1/groups/{hit['id']}"), json=body, timeout=15)
        if upd.status_code >= 300:
            print(f"  FAILED update group {m['name']}: HTTP {upd.status_code} {upd.text}")
            continue
        print(f"  Updated group description: {m['name']}")
        changes += 1
    return changes, created


def apply_rules(session, drift: dict, live_rules: dict[str, dict],
                name_to_id: dict[str, str], dry_run: bool) -> int:
    changes = 0
    for name in drift["missing"]:
        spec = drift["desired_map"][name]
        target_ids = []
        missing_targets = []
        for g in spec.get("assignUserToGroups", []):
            if g in name_to_id:
                target_ids.append(name_to_id[g])
            else:
                missing_targets.append(g)
        if missing_targets:
            print(f"  SKIP rule {name}: target groups not yet created: {missing_targets}")
            continue
        if dry_run:
            print(f"  [DRY RUN] Would create rule: {name}")
            changes += 1
            continue
        body = {
            "type": "group_rule",
            "name": name,
            "conditions": {
                "expression": {
                    "type": spec.get("expression", {}).get("type", "urn:okta:expression:1.0"),
                    "value": spec.get("expression", {}).get("value", ""),
                }
            },
            "actions": {"assignUserToGroups": {"groupIds": target_ids}},
        }
        resp = session.post(api_url("/api/v1/groups/rules"), json=body, timeout=15)
        if resp.status_code >= 300:
            print(f"  FAILED create rule {name}: HTTP {resp.status_code} {resp.text}")
            continue
        rule_id = resp.json()["id"]
        print(f"  Created rule: {name}")
        changes += 1
        if spec.get("status", "ACTIVE") == "ACTIVE":
            act = session.post(api_url(f"/api/v1/groups/rules/{rule_id}/lifecycle/activate"),
                               timeout=15)
            if act.status_code >= 300:
                print(f"  WARN: rule {name} created INACTIVE: {act.text}")
            else:
                print(f"  Activated rule: {name}")

    for m in drift["mismatched"]:
        name = m["name"]
        if dry_run:
            print(f"  [DRY RUN] Would update rule: {name}")
            changes += 1
            continue
        rule = live_rules[name]
        target_ids = [name_to_id[g] for g in m["desired"].get("assignUserToGroups", [])
                      if g in name_to_id]
        # Rules can only be updated when INACTIVE
        session.post(api_url(f"/api/v1/groups/rules/{rule['id']}/lifecycle/deactivate"), timeout=15)
        body = {
            "type": "group_rule",
            "name": name,
            "conditions": {"expression": {
                "type": m["desired"].get("expression", {}).get("type", "urn:okta:expression:1.0"),
                "value": m["desired"].get("expression", {}).get("value", ""),
            }},
            "actions": {"assignUserToGroups": {"groupIds": target_ids}},
        }
        upd = session.put(api_url(f"/api/v1/groups/rules/{rule['id']}"), json=body, timeout=15)
        if upd.status_code >= 300:
            print(f"  FAILED update rule {name}: HTTP {upd.status_code} {upd.text}")
            continue
        if m["desired"].get("status", "ACTIVE") == "ACTIVE":
            session.post(api_url(f"/api/v1/groups/rules/{rule['id']}/lifecycle/activate"),
                         timeout=15)
        print(f"  Updated rule: {name}")
        changes += 1
    return changes


# ---------------- Output ----------------

def print_summary(schema_drift, group_drift, rule_drift):
    s_total = len(schema_drift["missing"]) + len(schema_drift["mismatched"]) + len(schema_drift["extra_managed"])
    g_total = len(group_drift["missing"]) + len(group_drift["extra"]) + len(group_drift["description_mismatch"])
    r_total = len(rule_drift["missing"]) + len(rule_drift["extra"]) + len(rule_drift["mismatched"])
    print(f"\n{'=' * 60}")
    print("OKTA RECONCILE — DRIFT SUMMARY")
    print(f"{'=' * 60}")
    print(f"  Profile attrs: {s_total}")
    print(f"    missing:       {len(schema_drift['missing'])}")
    print(f"    mismatched:    {len(schema_drift['mismatched'])}")
    print(f"    extra managed: {len(schema_drift['extra_managed'])}")
    print(f"  Groups:        {g_total}")
    print(f"    missing:       {len(group_drift['missing'])}")
    print(f"    extra:         {len(group_drift['extra'])}")
    print(f"    description:   {len(group_drift['description_mismatch'])}")
    print(f"  Group rules:   {r_total}")
    print(f"    missing:       {len(rule_drift['missing'])}")
    print(f"    extra:         {len(rule_drift['extra'])}")
    print(f"    mismatched:    {len(rule_drift['mismatched'])}")
    print(f"  TOTAL drift:   {s_total + g_total + r_total}")
    print(f"{'=' * 60}")
    for label, items in (
        ("Missing profile attrs", schema_drift["missing"]),
        ("Missing groups", group_drift["missing"]),
        ("Extra groups (not in desired)", group_drift["extra"]),
        ("Missing rules", rule_drift["missing"]),
        ("Extra rules (not in desired)", rule_drift["extra"]),
    ):
        if items:
            print(f"\n{label}:")
            for it in items:
                print(f"  - {it}")


def generate_report(schema_drift, group_drift, rule_drift, desired_meta, changes_applied=None):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Okta RBAC Foundation — Reconcile Report",
        f"\n**Generated:** {ts}",
        f"**Desired-state exported:** {desired_meta.get('exportedAt', 'unknown')}",
        f"**Tenant:** {desired_meta.get('oktaDomain', 'unknown')}",
        "",
        "## Drift Summary",
        "",
        "| Surface | Missing | Extra | Mismatched |",
        "|---------|---------|-------|------------|",
        f"| Profile attributes | {len(schema_drift['missing'])} | {len(schema_drift['extra_managed'])} | {len(schema_drift['mismatched'])} |",
        f"| Groups | {len(group_drift['missing'])} | {len(group_drift['extra'])} | {len(group_drift['description_mismatch'])} |",
        f"| Group rules | {len(rule_drift['missing'])} | {len(rule_drift['extra'])} | {len(rule_drift['mismatched'])} |",
        "",
    ]
    if changes_applied is not None:
        lines += [f"**Changes applied:** {changes_applied}", ""]

    def section(title, items):
        if not items:
            return
        lines.append(f"## {title}\n")
        for it in items:
            lines.append(f"- `{it}`")
        lines.append("")

    section("Missing profile attributes", schema_drift["missing"])
    section("Missing groups", group_drift["missing"])
    section("Missing group rules", rule_drift["missing"])
    section("Extra groups in tenant (not deleted by reconcile)", group_drift["extra"])
    section("Extra group rules in tenant (not deleted by reconcile)", rule_drift["extra"])

    if not any((schema_drift["missing"], schema_drift["mismatched"], schema_drift["extra_managed"],
                group_drift["missing"], group_drift["extra"], group_drift["description_mismatch"],
                rule_drift["missing"], rule_drift["extra"], rule_drift["mismatched"])):
        lines.append("**No drift detected** — live tenant matches desired state.\n")

    lines.append("---")
    lines.append("\n*Report generated by `scripts/okta/reconcile_config.py`*")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Reconcile Okta RBAC against desired-state.json")
    parser.add_argument("--in", dest="infile", default=str(DEFAULT_IN), help="Desired-state JSON path")
    parser.add_argument("--apply", action="store_true", help="Remediate drift (no deletion)")
    parser.add_argument("--dry-run", action="store_true", help="With --apply, preview without writing")
    parser.add_argument("--report", action="store_true",
                        help="Write markdown drift report to docs/reports/")
    args = parser.parse_args()

    desired = load_desired(Path(args.infile))

    mode = "apply" if args.apply else "audit"
    print(f"Okta RBAC Reconcile — mode: {mode}")
    print(f"Desired state: {args.infile}")
    print(f"  Exported at: {desired.get('exportedAt')}")
    if args.apply and args.dry_run:
        print("*** DRY RUN — no changes will be made ***")
    print()

    session, _ = get_session()
    print("Authenticated with Okta Management API")

    print("Fetching live tenant state...")
    live_schema = fetch_live_schema(session)
    live_groups = fetch_live_groups(session)
    id_to_name = {g["id"]: g["name"] for g in live_groups.values()}
    live_rules = fetch_live_rules(session, id_to_name)
    print(f"  Live: {len(live_schema.get('definitions', {}).get('custom', {}).get('properties', {}) or {})} "
          f"custom attrs, {len(live_groups)} groups, {len(live_rules)} rules")

    print("Computing drift...")
    schema_drift = diff_schema(desired.get("profileAttributes", []), live_schema)
    group_drift = diff_groups(desired.get("groups", []), live_groups)
    rule_drift = diff_rules(desired.get("groupRules", []), live_rules)

    print_summary(schema_drift, group_drift, rule_drift)

    changes_applied = None
    if args.apply:
        print("\nApplying remediation...")
        s_changes = apply_schema(session, schema_drift, args.dry_run)

        g_changes, created_ids = apply_groups(session, group_drift, args.dry_run)

        # Rebuild name_to_id: existing live groups + newly-created ones
        name_to_id = {g["name"]: g["id"] for g in live_groups.values()}
        name_to_id.update(created_ids)
        # For dry-run, stub ids for newly-"created" groups so rule-apply can show intended targets
        if args.dry_run:
            for name in group_drift["missing"]:
                name_to_id.setdefault(name, f"DRY_RUN_ID_FOR_{name}")

        r_changes = apply_rules(session, rule_drift, live_rules, name_to_id, args.dry_run)
        changes_applied = s_changes + g_changes + r_changes
        print(f"\nRemediation: {changes_applied} changes "
              f"({s_changes} schema, {g_changes} group, {r_changes} rule)")

    if args.report or args.apply:
        report = generate_report(schema_drift, group_drift, rule_drift, desired, changes_applied)
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d-%H%M")
        report_path = REPORTS_DIR / f"okta-rbac-foundation-{date_str}.md"
        report_path.write_text(report)
        print(f"\nReport saved: {report_path}")


if __name__ == "__main__":
    main()
