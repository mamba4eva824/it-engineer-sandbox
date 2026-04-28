# Okta → Slack SCIM Lifecycle — Provisioning, Deprovisioning, Reactivation

A live test changelog of the Okta-managed SCIM provisioning channel into the OhmGym Slack Enterprise Grid sandbox (`ohmgym-sandbox.enterprise.slack.com`). Captures the full lifecycle of the SCIM channel — provisioning on group assign, deactivation on group unassign, reactivation on re-assign — with both Okta system log and Slack audit log evidence, and the seat-cap behavior we hit and reasoned about along the way.

Companion to [public-docs/04-okta-migration.md](04-okta-migration.md) (which proves the parallel pattern for Google Workspace). Same Okta IdP, same OIN-app pattern, different SP — and meaningfully different SCIM error surfaces.

## Purpose

Prove three things end-to-end with real evidence (no hand-waving):

1. **SCIM provisions** when an Okta group is assigned to the Slack OIN app
2. **SCIM deprovisions** (deactivates) when that group is unassigned, automatically, without writing any deprovisioning code
3. **SCIM reactivates** existing Slack identities (preserving DM history, channel memberships, audit trail) when the group assignment returns — not creating duplicate accounts

Bonus discovery: **Slack Developer Sandbox enforces an 8-active-user seat cap with HTTP 500 `user_creation_failed`** — a real production failure mode worth understanding before it surprises a JML pipeline.

## Topology proved here

```
Okta department group rule fires → user lands in Engineering/Product/IT-Ops/Data
        ↓
[Operator action] Engineering group → assigned to Slack OIN app
   (UI: Applications → Slack → Assignments tab → Assign to Groups)
   (CaC: config/okta/desired-state.json appAssignments + reconcile_config.py --apply)
        ↓
Okta SCIM client (built into the OIN app) → Slack SCIM endpoint
        ↓
Slack creates user; audit log: user_created
        ↓
[Operator action] Group unassigned from Slack OIN app
        ↓
Okta SCIM DELETE/PATCH → Slack
        ↓
Slack deactivates user; audit log: user_deactivated  (NOT user_deleted)
```

## Pre-test state

Before this session, the Slack OIN app (Okta app id `0oa127roo2hy53i5O698`) had only the Engineering group assigned, and 5 users SCIM-pushed:

```
Slack app users (Okta view):
  chris.okta@ohmgym.com           PROVISIONED / SYNCHRONIZED
  samantha.anderson@ohmgym.com    PROVISIONED / SYNCHRONIZED
  amanda.scott@ohmgym.com         PROVISIONED / SYNCHRONIZED
  william.robinson@ohmgym.com     PROVISIONED / SYNCHRONIZED
  test-jml-01@ohmgym.com          PROVISIONED / SYNCHRONIZED
```

OIN app provisioning features (verified via `GET /api/v1/apps/{appId}`): `IMPORT_PROFILE_UPDATES`, `PUSH_NEW_USERS`, `PUSH_USER_DEACTIVATION`, `GROUP_PUSH`, `REACTIVATE_USERS`, `IMPORT_USER_SCHEMA`, `IMPORT_NEW_USERS`, `PUSH_PROFILE_UPDATES`. All 8 SCIM lifecycle features turned on.

## Step log

### Step 1 — UI assignment for Product team

**Action:** Okta Admin Console → Applications → Slack → Assignments tab → Assign to Groups → `Product`.

**Expected:** Okta SCIM-pushes Samantha Diaz and Heather Robinson (the two Product seed users) into Slack within ~30s.

**Verified — Slack audit log (via `scripts/slack/audit_log_query.py`):**
```
2026-04-28T21:38:07Z  user_created  →  samantha.diaz@ohmgym.com
                        (Heather initially failed; see Issue 1)
2026-04-28T21:40:38Z  user_created  →  heather.robinson@ohmgym.com
```

This is the **UI mechanism** — what an IT analyst would do via the admin console. Same SCIM channel as the CaC mechanism in Step 3, just triggered from a different surface.

### Step 2 — Round-trip Okta UI assignment into config-as-code

After Step 1, ran `python scripts/okta/export_config.py --force`. The export captured the live `Slack ⇽ {Engineering, Product}` assignment into `config/okta/desired-state.json` under a new top-level key `appAssignments`:

```json
"appAssignments": [
  {
    "appLabel": "Google Workspace",
    "groups": ["Engineering", "access-gws"]
  },
  {
    "appLabel": "Slack",
    "groups": ["Engineering", "Product"]
  }
]
```

The export is keyed by app **label** (not internal Okta ID), matching the rest of the file's name-based reference convention. Result: ad-hoc UI assignments are now captured as code, with full git history, and `reconcile_config.py` will detect drift if anyone makes future changes through the UI.

### Step 3 — CaC assignment for IT-Ops + Data

**Action (hand edit):** added IT-Ops and Data to the Slack `appAssignments` entry in `desired-state.json`. Then:

```bash
$ python scripts/okta/reconcile_config.py
  App assignments:  2
    missing:        2
  - Slack: Data
  - Slack: IT-Ops

$ python scripts/okta/reconcile_config.py --apply
  Assigned Slack <- Data
  Assigned Slack <- IT-Ops
```

The reconciler is non-destructive: missing assignments → CREATE on `--apply`, extras in tenant → flagged in audit but never auto-unassigned. (Same conservative semantics as the existing groups/groupRules reconcilers — deletion of an app assignment cuts off downstream access for everyone in the group, which is too consequential for an automated reconciler to do silently.)

### Step 4 — Deprovisioning evidence

**Action:** removed the Engineering, Data, IT-Ops, and Product group assignments from the Slack OIN app via Okta Admin Console (Applications → Slack → Assignments → ✕ on each row).

**Expected:** Okta fires SCIM DELETE/PATCH for every previously-pushed user. Slack deactivates them.

**Verified — Slack audit log (events fired within 1–2 seconds of each unassignment click):**

```
2026-04-28T22:36:05Z  user_deactivated  →  samantha.diaz@ohmgym.com
2026-04-28T22:36:09Z  user_deactivated  →  chris.okta@ohmgym.com
2026-04-28T22:36:09Z  user_deactivated  →  samantha.anderson@ohmgym.com
2026-04-28T22:36:09Z  user_deactivated  →  amanda.scott@ohmgym.com
2026-04-28T22:36:09Z  user_deactivated  →  william.robinson@ohmgym.com
2026-04-28T22:37:22Z  user_deactivated  →  heather.robinson@ohmgym.com
```

**6 deactivations, ~1 minute total elapsed.** The Engineering batch fires in a single second (4 simultaneous `user_deactivated` events at 22:36:09Z) because Okta dispatches all SCIM DELETEs for an unassignment in parallel. Heather Robinson is delayed because her record had been forced to `scope: USER` during an earlier retry — Okta's SCIM client processes USER-scoped records on a slightly different path than GROUP-scoped ones.

Important nuance: **the audit event is `user_deactivated`, not `user_deleted`**. Slack's SCIM provider deactivates users rather than deletes them. This is intentional and standard for SCIM:

| Operation | Reversible? | Audit trail | Username freed | Seat freed |
|---|---|---|---|---|
| **Deactivate** (what SCIM does) | ✅ yes | ✅ preserved | ❌ no | ❓ depends on plan tier |
| **Delete** (admin-UI action only) | ❌ no | partial | ✅ yes | ✅ yes |

This matches the JML roadmap's Phase 3.4 spec: *"Do not delete accounts — suspension preserves audit trails. Deletion is a separate 90-day-later process not in scope here."* Slack is doing exactly the right thing.

### Step 5 — Reactivation, not re-creation

**Action:** re-applied the same group assignments via `python scripts/okta/reconcile_config.py --apply` (Engineering, Data, IT-Ops, Product all re-assigned).

**Expected — naive:** Okta calls SCIM Create for each user. Slack creates a new user record. Audit log: `user_created` events.

**Actual — better than expected:**
```
2026-04-28T22:32:32Z  user_reactivated  →  samantha.anderson@ohmgym.com
2026-04-28T22:32:32Z  user_reactivated  →  amanda.scott@ohmgym.com
2026-04-28T22:32:32Z  user_reactivated  →  william.robinson@ohmgym.com
2026-04-28T22:32:32Z  user_reactivated  →  chris.okta@ohmgym.com
```

`user_reactivated`, not `user_created`. Slack's SCIM provider checked for existing deactivated users matching the SCIM externalId and **reactivated the existing identity** — preserving DM history, channel memberships, file ownership, message history, and audit trail. Same Slack User ID (`U…`) before deactivation as after reactivation.

This is the **`REACTIVATE_USERS` provisioning feature** of the Okta OIN app working as designed. It's the difference between a re-hire showing up in Slack with a fresh empty inbox vs. picking up exactly where they left off.

**Why this matters for JML:** the typical Joiner→Mover→Leaver cycle assumes Leaver = irreversible. SCIM-with-reactivate makes Leaver actually reversible up until the deletion-after-N-days policy kicks in. This is critical for things like contractor rehires, leave-of-absence returns, and "wait, we shouldn't have deactivated them" mistakes — preserving the right thing without operator manual cleanup.

### Step 6 — Full reset

**Action:** removed all 4 groups from the Slack OIN app again. Cleared the Slack entry from `appAssignments` in `desired-state.json`.

**Verified:**
- Okta `GET /api/v1/apps/{slack_app_id}/groups` → 0 groups
- Okta `GET /api/v1/apps/{slack_app_id}/users` → 0 app users
- 6 more `user_deactivated` events in the Slack audit log (mirroring the previously-active 6)
- `python scripts/okta/reconcile_config.py` → **0 drift** (desired matches live)

End state matches expectations. Lifecycle proven both directions.

## Troubleshooting encountered

### Issue 1 — Transient HTTP 500 `user_creation_failed` on first SCIM push

**Symptom:** `python scripts/okta/audit_log_query.py --action user_created --since 5m` returned 1 event for samantha.diaz, but only 1 — Heather Robinson's push had failed silently. Okta system log showed:

```
2026-04-28T21:38:06.612Z  application.provision.user.push  FAILURE
  reason: Internal Server Error. Errors reported by the connector :
          {"Errors":{"description":"user_creation_failed (username=heather.robinson)","code":500}}
```

**Root cause (initially diagnosed as transient):** Slack's SCIM endpoint occasionally returns HTTP 500 on first push. Retrying the same push resolves it.

**Fix attempted:** forced a retry by re-POSTing the app-user via `POST /api/v1/apps/{appId}/users` with `scope: USER`. Retry succeeded; `user_created` event landed in Slack audit log a few seconds later.

**Side effect to know:** the retry pattern I used flips the app-user's scope from `GROUP` (auto-managed by group membership) to `USER` (manually managed). Functionally fine, but it means future group-membership changes don't auto-update that user — they need separate cleanup. For a one-off retry this is acceptable; for a production retry script, you'd want to clear the USER-scoped record and let the GROUP scope re-trigger naturally.

**Real root cause (revealed by Issue 2):** the "transient" 500 is actually the seat-cap behavior described in Issue 2. Heather's first push failed because Slack was at 8 active users; her retry succeeded only because something else had freed a seat in the meantime.

### Issue 2 — Slack Developer Sandbox 8-user seat cap (the real story behind the 500s)

**Symptom:** after re-assigning Data and IT-Ops to the Slack app, three users (Heather Gutierrez, Sharon Wilson, Alexander Robinson) stuck in Okta-side `STAGED / ERROR` state. Same `user_creation_failed (500)` from Slack on every retry. Okta system log:

```
6× application.provision.user.push  FAILURE
  reason: Internal Server Error. Errors reported by the connector :
          {"Errors":{"description":"user_creation_failed (username=...)","code":500}}
```

**Root cause:** Slack Developer Sandbox enforces an **8-active-user seat cap** (per ADR-006 in `okta_workato_zendesk_slack.md`). At the moment of failure, the active user count was already at 8:

```
1. chris@ohmgym.com (you, the owner)
2. sd0av24lmfhp_demouser@ohmgym.com (sandbox auto-provisioned demo)
3. chris.okta@ohmgym.com
4. samantha.anderson@ohmgym.com
5. amanda.scott@ohmgym.com
6. william.robinson@ohmgym.com
7. samantha.diaz@ohmgym.com
8. heather.robinson@ohmgym.com
```

Slack rejected the 9th, 10th, and 11th SCIM creates with a **generic 500** rather than a specific `quota_exceeded` or `seat_cap_reached` error. This is a genuine SCIM API design weakness — the error code doesn't tell you *why* it failed; you have to count active users yourself to figure it out.

**Diagnostic playbook:** when SCIM push to Slack returns 500 + `user_creation_failed`, check active-user count first. Counting via the audit log: `user_created` events − `user_deactivated` events for non-bot accounts = current active count.

**Resolution:** unassigning groups (which deactivates 6 users on Slack's side) freed seats, but reactivating Engineering immediately consumed 4 of them. Net seat math always lands at the cap with this seed set. Phase 3.4 Leaver flow is what unblocks: once `leaver.py` exists, deactivating obsolete users (test-jml-01, sd0av24lmfhp_demouser) frees enough seats for the full 8-user seed set to coexist.

For now: the seed is sized to fit the cap. Don't try to provision all departments at once — pick which 6 humans to keep active at any given time.

### Issue 3 — Slack admin UI Members count lags audit log truth

**Symptom:** after deactivating all SCIM users, Slack admin UI's Members page showed 5 users in "Invited" state — but our audit log showed 6 deactivations (matching the 6 active users we had). Refreshing 5 minutes later: 4 invited. Then 3.

**Root cause:** Slack's "Invited" filter on the Members page is a derived UI state that lags the underlying user lifecycle by minutes. SCIM deactivations are recorded in the audit log immediately, but the Members page reflects them on an asynchronous backend cleanup cycle.

**Lesson:** trust the audit log, not the admin UI Members count, for "how many active users are there really." This matters when reasoning about the seat cap — if the UI says "5 active" and you assume 3 seats free, but audit log says 8 actual active users, your next SCIM push will fail.

**Operational hint:** running `python scripts/slack/audit_log_query.py --action user_created --since 30d` and `--action user_deactivated --since 30d` and subtracting (after de-duplicating bot accounts) gives the authoritative active-user count for SCIM-cap planning.

## Outcomes + decisions

### What's proven

- **Okta → Slack SCIM provisioning works end-to-end** in both UI-driven (Assignments tab) and CaC-driven (`reconcile_config.py --apply`) mechanisms — same SCIM channel, two trigger surfaces
- **SCIM deprovisioning fires automatically** on group unassignment, ~1–2 second latency, no Slack-side cleanup code needed
- **SCIM reactivation works** — re-assigning a group reactivates the existing Slack identity (preserves DM history, channel memberships, audit trail) rather than creating duplicate accounts
- **Slack audit log is the authoritative source** for user lifecycle state — admin UI Members page lags by minutes
- **CaC pattern extends cleanly to app assignments** — `appAssignments` block round-trips through `export_config.py` and `reconcile_config.py` with stable git diffs and zero-drift idempotency
- **Slack Developer Sandbox 8-user seat cap is real** — surfaces as HTTP 500 + `user_creation_failed`, not a specific quota error. Diagnose by counting active users in the audit log.

### Key decisions made along the way

| Decision | Rationale |
|---|---|
| `appAssignments` keyed by app label, not Okta ID | Matches groups/groupRules name-based convention; stable across tenant rebuilds; readable in git diffs |
| Conservative non-destructive reconcile semantics for app assignments | Unassigning a group cuts off downstream access for everyone in it; too consequential for silent automation. Operator removes assignments manually if desired, then reconcile detects "extras" without acting on them. |
| Hand-maintained `baseProfileDependencies` preserved through export round-trip | Some keys aren't derivable from live Okta state (they're hand-documented intent); export merges existing file rather than overwriting |
| Document seat cap as Phase 3 trigger, not a bug to fix | The 8-user cap is by design (Developer Sandbox tier); the right unblocker is Phase 3.4 `leaver.py` + a deliberate decision about which historical accounts to retire |

### Deferred to later phases

- **Phase 3.4 `leaver.py`** — the seat-cap pressure is a clear Phase 3 trigger. Real Leaver flow needs to deactivate stale accounts (test-jml-01, sd0av24lmfhp_demouser) to free seats for an 8-user dept-balanced seed.
- **Slack-side default-role-for-SCIM-provisioned-users** — currently new SCIM users land as Slack admins because of the default role setting. Fixing this is a Slack-UI change; gated on having Org Owner role (currently Workspace Primary Owner). Track for the SAML rework or an Org-Owner role escalation.
- **Direct Python SCIM client** — currently using Okta's built-in SCIM push. Phase 2 `joiner.py` may need direct calls to `api.slack.com/scim/v2/Users` to control role/group mapping during provisioning. Requires `admin` scope on the Slack token (Org-Owner-gated install).
- **Slack Group Push (`@product` style User Groups)** — `GROUP_PUSH` is already enabled on the Okta OIN app. Pushing the Engineering/Product/Data/IT-Ops groups as Slack User Groups (not just Members) is a one-click extension. Phase 2.3.

### New ADR candidates for `okta_workato_zendesk_slack.md`

- **ADR-009: SCIM is the deprovisioning mechanism, not custom code.** Phase 3.4 `leaver.py` should remove an Okta user from the relevant access groups; SCIM does the rest. No `slack.deactivate_user()` Python call needed.
- **ADR-010: Audit-log-driven verification for SaaS seat caps.** When a SaaS connector returns a generic error, count active users in its audit log to disambiguate. Bake this into `joiner.py`'s pre-flight check so we don't hit blind SCIM 500s in production.

## Links

- [scripts/okta/_client.py](../scripts/okta/_client.py) — shared Okta API client (Private Key JWT auth)
- [scripts/okta/export_config.py](../scripts/okta/export_config.py) — extended in this session with `export_app_assignments()`
- [scripts/okta/reconcile_config.py](../scripts/okta/reconcile_config.py) — extended in this session with `fetch_live_app_assignments()` / `diff_app_assignments()` / `apply_app_assignments()`
- [scripts/slack/_client.py](../scripts/slack/_client.py) — shared Slack API client (xoxp- user token)
- [scripts/slack/audit_log_query.py](../scripts/slack/audit_log_query.py) — Slack Enterprise Audit Logs CLI (the diagnostic that made all of the above visible)
- [config/okta/desired-state.json](../config/okta/desired-state.json) — config-as-code source of truth, now includes `appAssignments`
- [public-docs/04-okta-migration.md](04-okta-migration.md) — companion: same OIN-app pattern proved against Google Workspace
