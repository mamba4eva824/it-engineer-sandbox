# Okta Workflows — Onboarding Flow Build Guide

**Status:** Build guide (follow this in the Workflows console)
**Pattern:** Scheduled flow that activates STAGED users on their start date
**Trigger:** Daily scheduled flow
**Source of truth:** Okta `profile.startDate` custom attribute
**Companion to:** Offboarding flow (Headspace pattern) and Mover flow

---

## What this flow does

Once a day at 5:00 AM Pacific, this flow:

1. Lists all Okta users whose `profile.startDate` equals today
2. Filters to those still in `STAGED` status (not already activated)
3. For each match: activates the user, optionally assigns them to a welcome group, posts a notification to `#it-onboarding` in Slack
4. If anything fails for a given user, posts an error to `#it-onboarding-errors` and continues processing the rest

This is the "Option B" architecture from the conversation earlier: scheduled flow + List Users with Search filtering on `startDate`. It's the production-tested pattern (Headspace ran exactly this) and it handles the case the User Activated event card cannot — *activating users on the right calendar day, regardless of when they were created in Okta*.

---

## Why this pattern over alternatives

| Pattern | Why not |
|---|---|
| User Activated event card | Fires on activation, not start date. If HR creates the user a week early, they'd be activated immediately. |
| Workday Pre-Start Interval | Native Workday integration ignores termination/start interval reliably; documented quirk. |
| Real-time HRIS event hook | Requires HRIS webhook setup + paid Workflows tier in some configurations; more moving parts than scheduled flow needs. |
| Manual IT activation | The whole point is to eliminate this. |

The scheduled-flow pattern works on every Workflows tier, has a single deterministic trigger (the schedule), and handles the timezone-correct "activate on start date" semantics naturally because you control when "today" gets evaluated.

---

## Prerequisites — set these up before building the flow

### 1. Custom profile attribute

Add `startDate` to the Okta user profile schema:

- **Variable name:** `startDate`
- **Display name:** `Start Date`
- **Data type:** `string` (ISO 8601 date format `YYYY-MM-DD`)
- **Description:** `Employee start date — used by onboarding workflow`
- **User permission:** Read-only (only HR/IT can write)

If you're managing the schema via Terraform (recommended, see `10-okta-terraform-cicd.md`), this is an `okta_user_schema_property` resource.

### 2. Slack connection in Workflows

In Workflows → Connections → New Connection → Slack:
- Authenticate as the Workflows service account user (not your personal account)
- Grant scopes: `chat:write`, `users:read`, `users:read.email`
- Save connection name as `Slack — IT Operations`

### 3. Slack channels

- `#it-onboarding` — receives one success message per activated user
- `#it-onboarding-errors` — receives error messages
- Workflows service account must be invited to both

### 4. Test user

Create one test user in Okta with:
- `firstName: Test`, `lastName: NewHire-2026-05-15`
- `email: test.newhire@ohmgym.com`
- `profile.startDate: <today's date in YYYY-MM-DD>`
- `status: STAGED` (Okta default for newly created users not yet activated)
- `profile.department: Engineering` (so SCIM provisioning has something to work on)

This is what you'll use to validate the flow end-to-end.

---

## Flow architecture — the cards in order

```
┌─────────────────────────────────────────────────────────────┐
│ TRIGGER: Schedule Flow                                       │
│ Runs daily at 5:00 AM Pacific                                │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Date & Time → Now                                            │
│ Output: current UTC datetime                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Date & Time → Format Date                                    │
│ Input: Now output                                            │
│ Format: YYYY-MM-DD (matches Okta profile.startDate format)   │
│ Timezone: America/Los_Angeles                                │
│ Output: today's date as string                               │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ Okta → List Users with Search                                │
│ Search filter:                                               │
│   profile.startDate eq "{today}" and status eq "STAGED"     │
│ Limit: 200                                                   │
│ Output: List of user objects                                 │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ List → For Each                                              │
│ Input: List from List Users with Search                      │
│ Calls helper flow per user                                   │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
                    ┌──────────────────────┐
                    │  HELPER FLOW          │
                    │  activate-single-user │
                    └──────────────────────┘
```

The helper flow handles per-user logic. This is the standard Workflows pattern for iteration since there's no native loop — For Each calls a child flow once per item.

---

## Building the parent flow — step by step

### Step 1: Create the flow

- Workflows console → Flows → New Flow
- Name: `Onboarding — Daily Activation`
- Description: `Activates STAGED users whose startDate equals today. Runs daily at 5am PT.`
- Folder: `Production/JML/Onboarding`

### Step 2: Add the Schedule trigger

- Search for `Schedule Flow` in the trigger search
- Add it as the trigger
- Configure:
  - **Frequency:** `Daily`
  - **Time:** `5:00 AM`
  - **Timezone:** `America/Los_Angeles`

Note on the timezone: the trigger timezone determines when the flow *runs*, not what date math it does. The date formatting card later will explicitly convert to PT before formatting — even though the trigger is already in PT, being explicit about timezone in the date card makes the flow correct if someone changes the trigger timezone later.

### Step 3: Add Date & Time → Now

- After the trigger, add card `Date & Time` → `Now`
- No inputs to configure
- Output: current datetime in UTC

### Step 4: Add Date & Time → Format Date

- After Now, add card `Date & Time` → `Format Date`
- Inputs:
  - **Date:** drag from Now's `date` output
  - **Format:** `YYYY-MM-DD`
  - **Timezone:** `America/Los_Angeles`
- Output: a string like `2026-05-15`

This is the date that will be matched against `profile.startDate`.

### Step 5: Add Okta → List Users with Search

- After Format Date, add card `Okta` → `List Users with Search`
- Configure:
  - **Search filter:** This is where the magic happens. The search filter syntax:
    ```
    profile.startDate eq "{{date_formatted}}" and status eq "STAGED"
    ```
    Drag the formatted date string into the `{{date_formatted}}` placeholder. The literal text in the field will end up something like:
    ```
    profile.startDate eq "2026-05-15" and status eq "STAGED"
    ```
  - **Limit:** `200` (more than enough for a single day's onboarding cohort; if you ever exceed this, the architecture needs a paging extension)
- Output: `users` (a list)

**Important Okta API note:** the `eq` operator on `profile.startDate` only works if the attribute is indexed. Custom string attributes are searchable by default in Okta, but if you've set up the schema with a non-default type, double-check. If the search returns empty when you know there should be matches, this is the first thing to verify.

### Step 6: Add Logic → If/Else (sanity check)

Before iterating, check that the list isn't empty. This isn't strictly necessary — For Each on an empty list is a no-op — but it gives you a clean branch for "no users to onboard today" that posts a heartbeat to Slack so you know the flow ran successfully.

- Add card `Logic` → `If/Else`
- Condition: `users.length > 0`
- **True branch:** continue to For Each
- **False branch:** Slack → Post Message to `#it-onboarding`, text `Daily onboarding flow ran at 5am PT — no users with startDate today.`

The heartbeat is optional but recommended; silent success is the worst kind of monitoring.

### Step 7: Add List → For Each

- On the True branch from Step 6, add card `List` → `For Each`
- Input: drag the `users` output from List Users with Search
- **Helper flow to invoke:** `activate-single-user` (you'll build this next)
- The For Each card will pass each user object to the helper flow

### Step 8: Save the parent flow

Save it. Don't enable yet — the helper flow doesn't exist.

---

## Building the helper flow — `activate-single-user`

The helper flow runs once per user. It's where the real work happens.

### Step 1: Create the helper flow

- New Flow → Helper Flow (not a triggered flow)
- Name: `activate-single-user`
- Folder: same as parent flow
- Input parameter: `user` (object — Okta user object)

### Step 2: Add Okta → Read User (defensive re-read)

You already have the user object from the parent flow's search, but reading it fresh handles the rare race condition where someone activated the user manually between the search and the helper flow execution.

- Card: `Okta` → `Read User`
- Input: `user.id` (drag from the helper flow's input)
- Output: fresh user object

### Step 3: Add Logic → If/Else (status check)

- Condition: `current_user.status == "STAGED"`
- **True branch:** continue to activation
- **False branch:** Slack → Post Message to `#it-onboarding-errors` with text `Skipped {{firstName}} {{lastName}} — status is {{status}}, expected STAGED`

This handles the "someone activated them manually after the search ran" case without crashing.

### Step 4: Add Okta → Activate User (on True branch)

- Card: `Okta` → `Activate User`
- Input: `user.id`
- **Send activation email:** `false` (you're going to send a Slack message instead; if you want the Okta email too, set this to `true`)

The Activate User card transitions the user from `STAGED` to `ACTIVE`. This is what triggers the downstream group-rule evaluation and SCIM provisioning. The user being added to `Engineering`, `AWS-Engineering`, etc. happens as a side effect of becoming ACTIVE — it's not something this flow handles directly.

### Step 5: Add Slack → Post Message (success notification)

- Card: `Slack` → `Post Message`
- Connection: `Slack — IT Operations`
- Channel: `#it-onboarding`
- Message:
  ```
  ✅ Activated {{firstName}} {{lastName}} ({{email}}) — Department: {{department}}
  Start date: {{startDate}}
  Okta admin: https://integrator-2367542.okta.com/admin/user/profile/view/{{id}}
  ```

Drag the user object's fields into the placeholders. The link to the admin profile is helpful for IT to spot-check after the fact.

### Step 6: Add an error branch

Workflows has a per-card error branch — the orange dot on the bottom of cards. For both the Activate User and the Post Message cards, wire the error branch to:

- Slack → Post Message to `#it-onboarding-errors`
- Message:
  ```
  ⚠️ Failed to activate {{firstName}} {{lastName}} ({{email}})
  Error: {{error.message}}
  Card: {{error.cardName}}
  ```

Without this, a single user's failure would halt the whole flow. The error branch lets you log the problem and continue to the next user.

### Step 7: Save the helper flow

Save and enable it. Helper flows must be enabled before the parent flow can call them.

---

## Testing — before you flip the production switch

### Test 1: Manual trigger with the test user

- Open the parent flow
- Click `Test` (top right)
- The flow runs once, immediately, regardless of the schedule
- Verify:
  - List Users with Search returns at least the test user
  - For Each iterates
  - Helper flow runs successfully
  - Test user moves from STAGED to ACTIVE
  - Slack message appears in `#it-onboarding`

### Test 2: Empty result

- Change the test user's `startDate` to tomorrow
- Run the parent flow manually
- Verify:
  - List Users with Search returns empty
  - The If/Else heartbeat branch fires
  - Slack message appears: "no users with startDate today"
  - Helper flow does not run

### Test 3: Error handling

- Temporarily break the Slack connection (revoke the auth token in Slack admin, or rename the channel)
- Make sure a test user has today's startDate
- Run the parent flow manually
- Verify:
  - Activate User succeeds (status changes to ACTIVE)
  - Slack post fails
  - Error branch fires
  - Error message attempts to post to `#it-onboarding-errors`
  - The Slack failure should also fail in the error branch (this is fine — it surfaces the connection issue in the Workflows execution log)

After testing, restore the Slack connection and reset the test user's status.

### Test 4: Multiple users in one cohort

- Create 3 test users with the same startDate (today)
- All three in STAGED status
- Run the parent flow manually
- Verify:
  - List returns 3 users
  - For Each iterates 3 times
  - 3 Slack messages appear in `#it-onboarding`
  - All 3 users are ACTIVE

---

## Enabling the production schedule

Once all four tests pass:

1. Open the parent flow
2. Toggle the flow to `On` (top-right corner)
3. Verify the next scheduled run time is shown correctly (`Next run: tomorrow at 5:00 AM PT`)
4. Set a calendar reminder to check `#it-onboarding` tomorrow morning to confirm the first scheduled run

---

## What this flow does NOT do

Worth being explicit about so the interview answer is honest:

- **It does not create users.** Users must already exist in Okta in STAGED status with their `startDate` populated. That's HR's job (or the HRIS-to-Okta sync's job).
- **It does not assign groups.** Group assignment is handled by the Okta group rules (e.g., `user.department == "Engineering"` → `Engineering` group), which evaluate automatically when the user becomes ACTIVE.
- **It does not provision downstream apps.** SCIM provisioning to Slack/Google Workspace/AWS is triggered by group membership, which is triggered by ACTIVE status. This flow's job ends at the activation; the rest is configured tenant state (which lives in Terraform per `10-okta-terraform-cicd.md`).
- **It does not send the welcome email to the new hire.** That can be added as another card after the Slack message — `Email — Send Email` to the user with their Okta sign-in link. Decide based on whether HR or IT owns the welcome email.
- **It does not handle pre-start access requests.** "Sarah needs access to a specific Drive 2 days before she starts" is a separate flow.

---

## Common gotchas (from real builds of this pattern)

1. **Timezone mismatch.** The `Now` card returns UTC. If you don't explicitly format with the right timezone, you'll activate users a day early or late depending on when the flow runs. Always use `Format Date` with explicit timezone for date comparisons.

2. **`startDate` data type drift.** If someone in Okta admin changes the schema attribute from string to date, the search filter will silently break. Lock down schema editing permissions or manage via Terraform.

3. **Status not STAGED.** Okta has multiple non-active states: `STAGED`, `PROVISIONED`, `RECOVERY`, `LOCKED_OUT`, `PASSWORD_EXPIRED`, `SUSPENDED`, `DEPROVISIONED`. The flow only handles STAGED. If your HRIS sync creates users in PROVISIONED instead, the search filter needs adjustment. Check what your sync actually produces with a test user.

4. **Default role for SCIM-provisioned Slack users.** When the activated user gets SCIM-provisioned to Slack, Slack assigns them a default role. If that default is `Workspace Admin` instead of `Member`, your new hires accidentally get admin rights. Verify the default role in the Slack SCIM app settings before this flow goes live.

5. **Search filter limit.** `List Users with Search` returns up to 200 in one call. For a normal company this is fine; for a large M&A onboarding cohort (200+ on the same day) you'd need pagination. Worth noting in the flow's description.

6. **Helper flow not saved as enabled.** A common mistake — the helper flow must be enabled, not just saved. The For Each card silently fails to invoke a disabled helper flow.

---

## Operational instrumentation

The flow has visibility through three channels:

- **Slack** — `#it-onboarding` for successes, `#it-onboarding-errors` for failures
- **Workflows execution log** — every run is captured with full input/output of each card; available in Workflows console → Executions
- **Okta system log** — `user.lifecycle.activate` events, queryable via API or the admin UI

For SOC 2 evidence: the Okta system log is the durable audit record. The Slack channel is for human awareness. The Workflows execution log is for debugging.

---

## Connection to the rest of the sandbox

This flow is one corner of the JML triplet:

| Flow | Purpose | Trigger |
|---|---|---|
| **Onboarding (this doc)** | Activate STAGED users on their start date | Daily 5am PT scheduled |
| **Mover** | Update group memberships when department changes | User Updated event |
| **Offboarding** | Deactivate users on Google Sheet termination dates | Daily 5pm PT scheduled |

All three flows share the same architectural assumption: **Workflows handles runtime orchestration; Terraform handles tenant configuration; group rules + SCIM handle the downstream side-effects.** Workflows doesn't directly create groups, assign apps, or provision SCIM connections — those are Terraform-managed. The flow just transitions user status, and the configured tenant state takes care of the rest.

This is the two-tool architecture from `10-okta-terraform-cicd.md` in operation: the seam between Workflows and Terraform is at group rules and event hooks, both of which are Terraform-managed (the rules) or Terraform-registered (the hooks).

---

## Interview talking points

- **"Event-driven workflows the Workflows builder can't fully express"** — this *is* a Workflows-buildable flow, but the design choices (scheduled vs. event, helper flow for iteration, error branches per card) are the senior signal. Knowing when Workflows is the right tool is as valuable as knowing when it's not.
- **Headspace-validated pattern** — same architecture that drove the 90% IT overhead reduction in the resume; this isn't theoretical, it's the production pattern translated to a sandbox tenant
- **Schedule + filter is more reliable than event hooks for date-based JML** — User Activated fires when activation happens, not when the start date arrives; the scheduled-flow pattern is timezone-correct because date math runs on a known cadence
- **Error branches per card** — silent failures are how onboarding flows lose user trust; explicit error routing to a dedicated channel is operational hygiene
- **Helper flows for iteration** — there's no native for-loop in Workflows; helper flows are the idiom. Demonstrates fluency in the platform's actual constraints.
- **Bounded scope** — the flow's job is "transition user status." Group assignment, SCIM provisioning, app access — those are owned by Terraform-managed tenant config, not by the flow. Knowing what *not* to put in a Workflow is a senior-engineering observation.
