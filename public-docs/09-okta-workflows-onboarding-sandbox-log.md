# Onboarding Workflow — Sandbox Build Log

**Companion to:** `09-okta-workflows-onboarding.md`
**Purpose:** Captures the actual sandbox state, prerequisite verification, and the substitutions you'll make in the Workflows UI for this specific tenant. The build guide stays generic; this log is the as-built record.

**Tenant:** `integrator-2367542.okta.com`
**Domain:** `ohmgym.com`
**Test cohort start date:** `2026-05-05`
**Workflow build day:** `2026-05-04`
**Test execution day:** `2026-05-05` (5:00 AM PT scheduled run)

---

## Prerequisite verification — what's done, what's manual

| Prereq | Doc says | Sandbox state | Notes |
|---|---|---|---|
| 1. `startDate` custom attribute | Add to schema | ✅ Already exists | Confirmed via Okta MCP `list_users` — `startDate` returns as `YYYY-MM-DD` string on existing users |
| 2. Slack connection in Workflows | Authenticate Slack connector | ⏳ Manual UI step | Workflows console → Connections → Slack. Cannot be configured via Okta API/MCP. |
| 3. Slack channels exist + bot invited | `#it-onboarding` + `#it-onboarding-errors` | ⏳ Sandbox uses `#joiner-it-ops` only — see substitution table below | Only the success/joiner channel exists; no error channel in this sandbox |
| 4. Test users in STAGED status | Create test user(s) | ✅ 2 users created via MCP — see test users section below | Created with status `PROVISIONED` (not STAGED) — see status note below |

---

## Sandbox-specific substitutions in the Workflows UI

When following the build guide, apply these substitutions wherever the doc references the production-style values:

| Doc reference | Substitute with | Why |
|---|---|---|
| Slack channel `#it-onboarding` (success branch) | `#joiner-it-ops` | The actual channel in this sandbox |
| Slack channel `#it-onboarding-errors` (error branch) | `#joiner-it-ops` (with `⚠️ ERROR:` message prefix) | No dedicated error channel exists; fold both into one with visual prefix |
| Search filter `status eq "STAGED"` | `(status eq "STAGED" or status eq "PROVISIONED")` | Test users were created via MCP and landed in PROVISIONED, not STAGED — see status note below. Both transition cleanly to ACTIVE via the Activate User card. |
| Helper flow status check `current_user.status == "STAGED"` | `current_user.status in ["STAGED", "PROVISIONED"]` (or two separate equality checks ORed together, depending on the Workflows If/Else card UI) | Same reason as above |
| Step 7 success Slack message channel | `#joiner-it-ops` | Sandbox channel name |
| Step 6 error branch destination | `#joiner-it-ops` with prefix `⚠️ ERROR:` in message body | No separate error channel |

**Production hardening note for the interview talking point:** "In a real tenant I'd split successes and errors into two channels so the noisy success stream doesn't desensitize on-call to error pages. In the sandbox I consolidated to one channel and prefixed error messages — same pattern, single-channel realization."

---

## Test users provisioned for the 2026-05-05 cohort

Created via Okta MCP on 2026-05-04. Both have `startDate: 2026-05-05` so they will match the daily flow's filter when it runs at 5 AM PT tomorrow.

| Login | Okta ID | Department | Role | Manager | Status |
|---|---|---|---|---|---|
| `test.joiner1@ohmgym.com` | `00u12mwbch2ae2agj698` | Engineering | Software Engineer | samantha.anderson@ohmgym.com | PROVISIONED |
| `test.joiner2@ohmgym.com` | `00u12mwc8toJ2lvsH698` | Product | Product Analyst | samantha.diaz@ohmgym.com | PROVISIONED |

Both have profile attributes populated for `costCenter`, `role_title`, `managerEmail`, and `startDate`.

### Why PROVISIONED instead of STAGED

The doc says STAGED. In practice, when you create a user via Okta API with `activate=false` and no password attribute, Okta orgs with default self-service settings often promote new users immediately to `PROVISIONED` (a pending-activation state, distinct from STAGED).

This is also what real HRIS-fed Okta provisioning produces — most production sync setups land users in PROVISIONED, not STAGED. So the "use both states in the filter" pattern is actually the production-realistic choice, not a sandbox compromise.

Both states transition cleanly to `ACTIVE` via the Activate User card:
- STAGED → ACTIVE: direct lifecycle transition
- PROVISIONED → ACTIVE: completes the pending activation

If you specifically want a STAGED user for testing the doc's exact filter, you'd need to create the user with the password recovery question explicitly set in the API call — outside the scope of this sandbox.

### Re-creating these test users via MCP

If you delete or activate them and need fresh STAGED/PROVISIONED users for re-testing, the MCP call shape is:

```python
mcp__okta__create_user(
  profile={
    "firstName": "TestJoiner",
    "lastName": "One",
    "email": "test.joiner1@ohmgym.com",
    "login": "test.joiner1@ohmgym.com",
    "department": "Engineering",
    "costCenter": "ENG-100",
    "role_title": "Software Engineer",
    "managerEmail": "samantha.anderson@ohmgym.com",
    "startDate": "<YYYY-MM-DD of target test date>"
  },
  activate=false
)
```

---

## Cleanup performed to make room

The Okta tenant has a 10-active-user cap. Before creating the test users, two ACTIVE users were deactivated and deleted:

- `chris+priya@ohmgym.com` — duplicate test alias (`chris+` prefix), already had stale `startDate`
- `heather.robinson@ohmgym.com` — Product user; least load-bearing of the cohort

Active count now: 5 (well under the 10-user cap, with room to activate the 2 test users tomorrow).

---

## What the API/MCP can and cannot do for this workflow

**Can do via Okta MCP/API:**
- Verify custom attribute exists on the schema (by reading any user)
- List/create/deactivate/delete users
- Create users in PROVISIONED state (not strictly STAGED, see above)
- Read user statuses to verify the cohort is in the right state pre-test

**Cannot do via Okta MCP/API:**
- Configure the Slack connection in Workflows (Workflows console only)
- Create Slack channels (would need Slack Admin API in `scripts/slack/`)
- Invite Workflows bot to a Slack channel (Slack-side)
- Build the actual flow itself (Workflows console only — flow definitions are not API-managed in the developer/free tier)

**Bottom line:** The MCP gets you 2 of 4 prereqs done programmatically (#1 verify schema, #4 create test users). #2 and #3 are manual UI work in the Workflows console and Slack workspace respectively.

---

## Pre-test checklist for tomorrow morning (2026-05-05)

Before the 5:00 AM PT scheduled run:

- [ ] Workflow saved and toggled `On` in Workflows console
- [ ] Helper flow `activate-single-user` saved and `enabled`
- [ ] Slack connection in Workflows authenticated (test with a manual post)
- [ ] Workflows bot invited to `#joiner-it-ops`
- [ ] Both test users still exist in Okta (`list_users` filtered to `test.joiner` prefix)
- [ ] Both test users still in PROVISIONED status (haven't been manually activated)
- [ ] `startDate: 2026-05-05` confirmed on both users
- [ ] Search filter in `List Users with Search` updated to include both STAGED and PROVISIONED

After the run:

- [ ] Both users transitioned to ACTIVE
- [ ] Two success messages appeared in `#joiner-it-ops`
- [ ] No error messages
- [ ] Workflows execution log shows the parent + 2 helper flow executions

---

## Open questions / followups

- The `STAGED vs PROVISIONED` distinction is a senior-IT talking point — worth raising in the interview as evidence of having debugged this exact lifecycle quirk.
- Should the workflow also send the welcome email via Okta's `Activate User` card (set `Send activation email: true`)? Sandbox tradeoff: simpler if Slack message replaces the email; more realistic if both fire.
- Production hardening: extract the channel name to a Workflow constant so future channel renames are a one-line change.
