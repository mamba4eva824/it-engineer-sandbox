# JML Orchestration Project: Implementation Guide

Unified Joiner/Mover/Leaver automation across Okta, Google Workspace, Slack, and Zendesk — built three ways (Python, Workato, Okta Workflows) with a self-service Slack bot on top.

Target: 5 weeks at 1-2 hours/weekday plus longer weekend sessions. Built for the Netflix Enterprise SaaS Engineer role.

---

## Project Context for Claude Code

This document is both a roadmap for the human and a working context file for Claude Code sessions. When Claude Code is invoked to work on this project, it should:

1. Read this file first to understand the current phase and the architectural decisions already made.
2. Check `CLAUDE.md` for repo-wide conventions (Python against SaaS APIs, dry-run by default, idempotent scripts).
3. Check `it_ops_lab.md` for the broader sandbox context — this JML project supersedes Phase 3 and 4 of that plan.
4. Prefer extending existing patterns in `scripts/auth0/` and `scripts/gws/` rather than reinventing. The Okta migration should preserve the `generate_users.py` → `provision_users.py` → sync pattern.

When any phase is completed, update the **Phase Status** table at the bottom of this file.

---

## Architectural Decisions (ADRs)

These are locked-in decisions. Do not relitigate without explicit human direction.

### ADR-001: Okta replaces Auth0 as the IdP
The Auth0 trial expired. Okta Workforce Identity 30-day trial includes Workflows and Lifecycle Management, which directly map to the Netflix JD. All existing Auth0 scripts stay in the repo as historical reference but are not actively maintained.

### ADR-002: Build Python first, port to Workato second
Python implementation forces understanding of every API call and error case. Workato port is the contrast piece. Skipping the Python step produces tutorial-quality output, not engineer-quality output.

### ADR-003: One system at a time, end-to-end
Do not stand up Okta, Zendesk, and Workato in parallel. Each week ends with something that works end-to-end for the systems added to that point.

### ADR-004: Zendesk plays two roles
(a) Provisioning target for users on the Support team who need agent seats. (b) Audit trail system — every JML event creates a ticket documenting what happened. This is non-negotiable; the audit ticket is the compliance story.

### ADR-005: Automate the 80%, ticket the 20%
For Mover flows, deterministic changes (OU, groups, channels) are automated. Non-deterministic changes (specific Figma files, custom Notion pages) become a Zendesk ticket assigned to the user's new manager with structured context.

### ADR-006: Sandbox tenants use a representative user subset
Slack Developer Program sandbox caps at 8 users. Okta Integrator Free plan caps at 10 users. Google Cloud Identity Free caps at ~10. Do not try to provision all 100 NovaTech users. Pick 5-8 across 3 departments that the three caps can accommodate. The interview story is architecture, not test data scale.

### ADR-007: Keep scope to GWS + Slack + Zendesk
The Netflix JD names these three. Do not add Jira, GitHub provisioning, or device management. Extras dilute.

---

## Trial Clock Management (Critical)

| Platform | Duration | When to Start | Expires |
|----------|----------|---------------|---------|
| Okta Workforce Identity | 30 days | Week 1 Day 1 | End of Week 4 |
| Zendesk Suite | 14 days | Week 3 Day 1 | End of Week 4 |
| Workato Developer Sandbox | Permanent (100k events) | Week 4 Day 1 | Usage-capped |
| Slack Developer Program | 6 months (renewable) | Week 2 Day 3 | Week 26 |

**Do not start Zendesk on Week 1.** The 14-day clock will expire before you need it in Week 3. Starting Okta and Zendesk on the same day wastes half the Zendesk trial.

---

## Phase 1 — Okta & Zendesk Foundations (Week 1)

**Goal**: Okta trial active with 20 users migrated from Auth0 patterns. Zendesk trial active with ticket forms, groups, API token, and MCP server wired to Claude Code.

### Tasks

#### 1.1 Okta tenant setup (Days 1-2)
- [x] Okta Integrator Free tenant provisioned at `integrator-2367542.okta.com`
- [x] API Services app created with Private Key JWT client-credentials auth; creds stored in `.env`:
  `OKTA_ORG_URL`, `OKTA_CLIENT_ID`, `OKTA_KEY_ID`, `OKTA_PRIVATE_KEY`, `OKTA_SCOPES`
- [x] Okta MCP server wired into `.mcp.json` via `run-okta-mcp.sh` wrapper (shares `.env` with scripts)
- [x] `scripts/okta/test_connection.py` — smoke test that prints granted scopes and exercises /groups, /users, /schemas reads
- [ ] **Scope: confirm `okta.schemas.manage` is enabled** in API Services app → Okta API Scopes, and that `OKTA_SCOPES` in `.env` lists all `*.manage` scopes the scripts need (restart Claude Code after `.env` edits so the MCP subprocess picks them up)

#### 1.2 RBAC foundation via config-as-code (Day 2)
The entire RBAC skeleton — 5 profile attributes, 10 department groups, 10 group rules — is defined in `config/okta/desired-state.json` and applied by `scripts/okta/reconcile_config.py`. Mirrors the proven `scripts/gws/` pattern (export → hand-edit → reconcile --apply).

**Manual-first bootstrap** (refresh Okta Admin Console navigation muscle memory):
- [ ] In Okta Admin Console, manually create **Engineering** and **IT-Ops** groups (empty is fine)
- [ ] Run `python scripts/okta/export_config.py` — captures the two manually-created groups into `config/okta/desired-state.json`
- [ ] Reconcile the rest via script:
  ```bash
  python scripts/okta/reconcile_config.py --audit          # preview drift
  python scripts/okta/reconcile_config.py --apply --dry-run # show intended writes
  python scripts/okta/reconcile_config.py --apply          # create 8 remaining groups + 10 rules + 5 profile attrs
  ```
- [ ] Verify: `python scripts/okta/export_config.py` produces zero-change diff (round-trip test)

**What's in `config/okta/desired-state.json`:**
- Profile attributes (optional, not required — safe for pre-existing users): `department` (enum), `role_title`, `costCenter` (regex `^[A-Z]{2,4}-\d{3,4}$`), `managerEmail` (regex `.+@ohmgym\.com$`), `startDate` (ISO date)
- 10 OKTA_GROUP groups: Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing
- 10 group rules: `rule-dept-{snake_case_dept}` → `user.department == "{Department}"` → assign to matching group

User provisioning (actual user creation) is deferred to Phase 2 — once RBAC is solid, pick 5-8 users across 3-4 departments (respecting the 10-user Okta cap per ADR-006) via `scripts/okta/provision_users.py` (to be written).

#### 1.3 Zendesk trial setup (Days 3-4)
- [ ] Sign up for Zendesk Suite 14-day trial. **Do not sign up earlier — the clock is short**
- [ ] Create ticket forms: "Access Request", "JML Audit", "IT Incident"
- [ ] For "Access Request": custom fields for target app, business justification, duration, manager email
- [ ] For "JML Audit": custom fields for event type (Joiner/Mover/Leaver), user email, systems affected, automation run ID
- [ ] Create Zendesk groups: `it-ops-audit`, `l1-support`, `l2-support`
- [ ] Generate API token: Admin Center → Apps & integrations → APIs → Zendesk API. Store as `ZENDESK_API_TOKEN` in `.env`. Also store `ZENDESK_SUBDOMAIN` and `ZENDESK_EMAIL`
- [ ] Install `reminia/zendesk-mcp-server` from GitHub. Add to `.mcp.json` alongside existing servers
- [ ] Restart Claude Code, verify MCP server loads by asking Claude to list recent tickets

#### 1.4 Okta → GWS SAML re-federation (Day 5)
- [ ] In Okta, add the pre-built Google Workspace app from the Okta Integration Network (OIN)
- [ ] Configure SAML settings following the OIN guide
- [ ] Assign the app to the `Engineering` Okta group for initial testing
- [ ] Test SP-initiated and IdP-initiated flows with one migrated user
- [ ] Document differences vs. Auth0 manual SAML config in notes for Phase 1 writeup

#### 1.5 Okta → AWS IAM Identity Center SAML federation (DEFERRED)
Parallels the Okta → GWS federation in 1.4. Deferred out of Phase 1 scope to keep the initial phase focused on JML targets (GWS + Slack + Zendesk). The Auth0 → AWS SAML pattern (see `scripts/auth0/actions/aws-saml-attribute-mapping.js` + `public-docs/02-aws-saml-federation.md`) is the reference to port:
- Department → Permission Set mapping (IT-Ops → Admin, Engineering/Data → PowerUser, rest → ReadOnly)
- `RoleSessionName` = user email, `AccessLevel` = permission set, plus `department` and `role_title` as audit attributes
- Okta equivalent uses Attribute Statements on the OIN AWS app rather than Auth0 Actions — no custom JS required

When this phase fires, the department groups + profile attributes from 1.2 are the foundation the SAML assertion statements consume.

#### 1.6 Documentation (Weekend)
- [ ] Create `public-docs/04-okta-migration.md`
- [ ] Document: SAML config differences between Auth0 (manual) and Okta OIN, how Okta group rules + OIN attribute statements replace Auth0 Actions for attribute injection, what the Okta Integration Network abstracts away
- [ ] Update root `README.md` — add an "Identity Platform Migration" section noting the Auth0 → Okta move

### Exit criteria for Phase 1
- Okta tenant has 5 custom profile attributes, 10 department groups, and 10 department group rules — all provisioned via `scripts/okta/reconcile_config.py --apply` against `config/okta/desired-state.json`
- Round-trip test passes: `export_config.py` against the post-apply tenant yields zero git diff
- `docs/reports/okta-rbac-foundation-{date}.md` committed as demoable artifact
- 5-8 NovaTech users exist in Okta with correct `department` attribute driving auto-group membership (Phase 2 work)
- Zendesk trial active with ticket forms, groups, and API access
- Zendesk MCP server responding to Claude Code queries
- One test user successfully SSOs from Okta into GWS
- `public-docs/04-okta-migration.md` committed

### Phase 1 risks
- Okta group rules evaluate asynchronously after attribute changes — typically within 30 seconds on dev tenants but there is no documented upper bound. Verification tests should poll `list_group_users` until the membership appears, not sleep a fixed duration.
- `okta.schemas.manage` is a separate scope from `okta.groups.manage` — a common gotcha is enabling groups.manage and forgetting schemas.manage, which silently fails only the profile-attribute updates.
- Zendesk API tokens require "Token access" to be explicitly enabled in Admin Center → Apps & integrations → APIs → Zendesk API settings. This is not on by default.

---

## Phase 2 — Python Joiner Flow: Okta → GWS → Slack (Week 2)

**Goal**: A single Python entry point that, given an Okta user ID, provisions that user into GWS and Slack with proper error handling, compensating transactions on failure, and dry-run support.

### Tasks

#### 2.1 Joiner scaffold (Days 1-2)
- [ ] Create `scripts/lifecycle/joiner.py`. Entry signature: `python joiner.py --okta-user-id <id> [--dry-run]`
- [ ] Implement `fetch_okta_user(user_id)` — pull full profile including custom attributes
- [ ] Implement `build_provisioning_plan(user)` — returns a list of action dicts: `[{"system": "gws", "action": "create_user", "params": {...}}, ...]`
- [ ] In dry-run mode, print the plan and exit. **Do not touch any system yet**
- [ ] Run `--dry-run` against 3 test users across different departments. Verify plan is correct

#### 2.2 GWS provisioning (Day 3)
- [ ] Add `execute_gws_actions(plan)` to `joiner.py`. Reuse logic from `scripts/gws/provision_users.py` — port the user creation call, do not duplicate
- [ ] Key change from existing script: data source is the Okta user object, not `novatech_users.json`
- [ ] Verify: running joiner creates user in correct OU with correct manager, department, cost center
- [ ] Add structured logging — each action emits a JSON log line with `{action_id, system, status, duration_ms, error}`

#### 2.3 Slack provisioning (Day 4)
- [ ] Sign up for Slack Developer Program if not already done. Provision Enterprise sandbox
- [ ] Create Slack user groups mirroring departments: `engineering`, `it-ops`, etc.
- [ ] Create department channels: `#engineering`, `#it-ops`, plus shared channels `#general`, `#new-hires`
- [ ] Store Slack bot token and SCIM token in `.env`: `SLACK_BOT_TOKEN`, `SLACK_SCIM_TOKEN`
- [ ] Write `scripts/slack/provision_user.py` — creates Slack user via SCIM, adds to department user group, invites to department channel + shared channels
- [ ] Wire into `joiner.py` as `execute_slack_actions(plan)`
- [ ] Test end-to-end: Okta user ID → joiner → GWS user created + Slack user created + channels joined

#### 2.4 Compensating transactions (Day 5)
- [ ] Implement rollback logic. If action N fails, undo actions 1 through N-1 in reverse order
- [ ] Each system needs a `undo_*` function: `undo_gws_create_user(user_id)` suspends the account (do not delete — keeps audit trail); `undo_slack_create_user(user_id)` deactivates
- [ ] Test failure injection: temporarily break Slack credentials, run joiner, verify GWS user is suspended as rollback
- [ ] **Document explicitly in code comments**: "This rollback logic is what Workato handles natively in Phase 4. The lines of code here are the contrast point."

#### 2.5 Integration test (Weekend)
- [ ] Create a test Okta user via the Okta API (not the admin console — use the API so the whole flow is scriptable)
- [ ] Run `joiner.py` against it
- [ ] Verify correctness in GWS admin console and Slack workspace
- [ ] Tear down: run a manual cleanup script to suspend the test user in both systems

### Exit criteria for Phase 2
- `python scripts/lifecycle/joiner.py --okta-user-id <id>` successfully provisions across GWS and Slack
- Dry-run mode prints accurate plan without touching systems
- Rollback works: forced Slack failure results in GWS user suspension
- Structured logs written to `logs/joiner-<timestamp>.jsonl`

### Phase 2 risks
- Slack SCIM API quirks: user creation sometimes returns 201 but the user isn't immediately queryable. Add a 2-second sleep + verification step after creation.
- Slack free sandbox caps at 8 users. If hit, deactivate old test users before creating new ones.
- GWS Directory API eventual consistency: a user created in `/Engineering` OU may show as `/` for 30-60 seconds. Don't fail the joiner on this — log warning and move on.

---

## Phase 3 — Zendesk Integration, Mover, and Leaver Flows (Week 3)

**Goal**: Full JML lifecycle in Python. Every event produces a Zendesk audit ticket. Drift detection runs across all three downstream systems.

### Tasks

#### 3.1 Zendesk as provisioning target (Day 1)
- [ ] Write `scripts/zendesk/provision_agent.py` — creates Zendesk user, sets role (`end-user`, `agent`, `admin`), assigns to group
- [ ] In `joiner.py`, add logic: if user's Okta department is "Support" or "IT-Ops", call Zendesk agent provisioning
- [ ] Otherwise, user is created in Zendesk as `end-user` role so they can submit tickets

#### 3.2 Zendesk as audit trail (Day 2)
- [ ] Write `scripts/zendesk/create_audit_ticket.py` — creates a "JML Audit" ticket with structured custom fields
- [ ] Modify `joiner.py` to call audit ticket creation at the end of every successful run — ticket body contains the full provisioning log, JSON-formatted
- [ ] Ticket assigned to `it-ops-audit` group, status set to `solved` immediately (these are records, not actionable tickets)
- [ ] Test: run joiner, verify Zendesk ticket exists with complete log

#### 3.3 Mover flow (Day 3)
- [ ] Create `scripts/lifecycle/mover.py`. Signature: `python mover.py --okta-user-id <id> --new-department <dept> [--dry-run]`
- [ ] Implement state diff: compare user's current GWS OU, Slack user groups, Slack channels, Okta groups against what the new department requires
- [ ] Deterministic changes execute automatically: OU move, group changes, channel add/remove
- [ ] Non-deterministic flag: for custom app access (mock this with a `custom_apps` user attribute), create a Zendesk ticket assigned to the new manager with a checklist
- [ ] Ticket type: "Access Review Required — Mover: <user>". Contains: old department apps, new department apps, explicit ask for manager to confirm what transfers
- [ ] **Document the 80/20 decision** in code comments

#### 3.4 Leaver flow (Day 4)
- [ ] Create `scripts/lifecycle/leaver.py`. Signature: `python leaver.py --okta-user-id <id> [--dry-run]`
- [ ] **Ordering is security-critical**. Execute in this order: (1) Revoke all Okta sessions, (2) Deactivate Okta user, (3) Suspend GWS account, (4) Deactivate Slack user, (5) Downgrade Zendesk to `end-user` and remove from groups
- [ ] Create Zendesk ticket for the user's manager listing all access revoked + any data transfer needs
- [ ] **Do not delete accounts** — suspension preserves audit trails. Deletion is a separate 90-day-later process not in scope here
- [ ] Test against a test user. Verify all 5 systems reflect the change

#### 3.5 Drift detection (Day 5)
- [ ] Extend `scripts/lifecycle/sync_auth0_gws.py` → create `scripts/lifecycle/sync_okta_all.py`
- [ ] Pull user state from Okta (source of truth), compare against GWS, Slack, Zendesk
- [ ] Report categories: OU mismatch, missing from downstream, orphaned downstream, role mismatch
- [ ] On drift detected, post a Slack message to `#it-ops-alerts` with structured block kit formatting
- [ ] Add GitHub Actions workflow: `.github/workflows/drift-detection.yml` running the sync script on cron (hourly during work hours)

#### 3.6 Architecture documentation (Weekend)
- [ ] Create `public-docs/05-jml-architecture.md`
- [ ] Include sequence diagrams for Joiner, Mover, Leaver (use Mermaid, which renders on GitHub)
- [ ] Explain the 80/20 automation decision, the compensating transaction pattern, the suspension-vs-deletion choice
- [ ] This doc is what you screen-share in interviews

### Exit criteria for Phase 3
- Joiner, Mover, Leaver all work end-to-end with --dry-run support
- Every JML event creates a Zendesk audit ticket with structured custom fields
- Drift detection runs on cron and posts findings to Slack
- `public-docs/05-jml-architecture.md` committed with Mermaid sequence diagrams

### Phase 3 risks
- Zendesk trial expires end of week 4. Capture screenshots of ticket forms, ticket examples, and group configurations this week so the artifacts survive trial expiration.
- Mover flow has the most edge cases. Time-box the 80/20 split — if a change type isn't clearly in the "automate" bucket after 15 minutes of thought, put it in the ticket bucket and move on.
- Leaver ordering mistakes are the most consequential bug class. Write a test that asserts the order of operations.

---

## Phase 4 — Workato Port + Okta Workflows Comparison (Week 4)

**Goal**: Joiner flow rebuilt in Workato. Same Joiner flow partially rebuilt in Okta Workflows. A written three-way comparison committed.

### Tasks

#### 4.1 Workato Developer Sandbox setup (Day 1)
- [ ] Sign up at workato.com/sandbox
- [ ] Set up connectors: Okta, Google Workspace, Slack, Zendesk. Each requires its own OAuth or API key flow — budget 2 hours total
- [ ] Build a "hello world" recipe: trigger on Okta user created → post message to `#new-hires`. Validates all auth before building the real recipe

#### 4.2 Workato Joiner recipe (Days 2-3)
- [ ] Build the Joiner recipe in Workato. Structure:
  - Trigger: Okta `user.lifecycle.create` webhook
  - Step 1: Read user's department from Okta profile
  - Step 2: Create user in GWS in correct OU
  - Step 3: Create Slack user via SCIM, assign to user group
  - Step 4: Conditional — if department is "Support", create Zendesk agent
  - Step 5: Create Zendesk audit ticket
  - Step 6: Post welcome message in `#new-hires`
  - Error handling branch: retry 3x, then create P2 Zendesk ticket assigned to `it-ops-audit`
- [ ] Export the recipe definition as JSON. Commit to `workato/recipes/joiner.json`
- [ ] Screenshot the visual recipe builder. Commit to `public-docs/images/workato-joiner-recipe.png`

#### 4.3 Okta Workflows Joiner flow (Day 4)
- [ ] In Okta admin console, enable Workflows (included in trial)
- [ ] Build the same Joiner flow using Okta Workflows
- [ ] Expect to hit limitations: Workflows is great for Okta-native logic and has connectors for common apps, but multi-system orchestration with complex branching is harder than in Workato
- [ ] Build what you can. Where Workflows falls short, document it — that's the lesson
- [ ] Export the flow as a Workflows template JSON if possible. Commit to `okta-workflows/joiner.json`
- [ ] Screenshot the Workflows canvas. Commit to `public-docs/images/okta-workflows-joiner.png`

#### 4.4 Three-way comparison document (Day 5)
- [ ] Create `public-docs/06-orchestration-comparison.md`
- [ ] Structured comparison across: lines of code/blocks, time to build, error handling story, observability, cost, maintainability, who can modify it (engineer vs. IT analyst)
- [ ] Include a decision matrix: "When would you pick each?"
- [ ] Your opinion should be concrete and justified by building experience, not hand-waved

#### 4.5 Polish and push (Weekend)
- [ ] Update root `README.md` to reflect the three implementations
- [ ] Ensure all three Joiner implementations produce equivalent Zendesk audit tickets — this is the seam that proves they're functionally equivalent
- [ ] Commit everything, push to GitHub public

### Exit criteria for Phase 4
- Workato Joiner recipe working against the same test users Phase 2 used
- Okta Workflows Joiner built to whatever extent possible, limitations documented
- `public-docs/06-orchestration-comparison.md` committed with concrete opinions backed by build experience
- All three implementations produce functionally equivalent results

### Phase 4 risks
- Workato connector auth flows for GWS and Zendesk can be fiddly. If an auth flow fails twice, check Workato's connector documentation before assuming the issue is on your side.
- Okta Workflows' connector for Zendesk may not exist or be limited. That's fine — it's a data point for the comparison doc.
- Okta trial expires end of this week. Capture screenshots and export configs before expiration.

---

## Phase 5 — Self-Service Slack Bot + Portfolio Polish (Week 5)

**Goal**: A working `/access-request` Slack bot that ties Okta, Zendesk, and Workato together. Demo video recorded. Portfolio documentation polished for interview use.

### Tasks

#### 5.1 Slack bot scaffold (Days 1-2)
- [ ] Create `scripts/slack/access_request_bot.py` using Slack Bolt (Python)
- [ ] Register slash command `/access-request` in your Slack app configuration
- [ ] Implement modal open handler — form fields: target app (dropdown: Salesforce, Jira, Figma, Tableau), business justification (text), duration (30/60/90 days), manager email (auto-filled from Slack profile)
- [ ] On modal submit, create a Zendesk ticket with form "Access Request" and fill custom fields
- [ ] Respond in thread to user with ticket link

#### 5.2 Approval flow via Workato (Day 3)
- [ ] Build a second Workato recipe: "Access Request Approval"
- [ ] Trigger: Zendesk ticket created with form "Access Request"
- [ ] Step 1: Post to manager's Slack DM with Block Kit Approve/Deny buttons
- [ ] Step 2: Wait for button response (Workato supports this via resumable recipes)
- [ ] Step 3a (approve): Call Okta API to add user to requested group. Update Zendesk ticket with approval record. Post confirmation to user
- [ ] Step 3b (deny): Update Zendesk ticket with denial. Post to user with reason

#### 5.3 Audit trail and observability (Day 4)
- [ ] Every step updates the Zendesk ticket with a timestamped internal note
- [ ] Final ticket state contains: original request, approval chain, Okta audit log link (URL to the Okta system log entry), actual access granted timestamp
- [ ] Build `scripts/reports/access_request_report.py` — pulls all "Access Request" tickets from Zendesk, generates weekly summary with approval rate, avg time-to-grant, top requested apps

#### 5.4 Demo video (Day 5)
- [ ] Record a 3-minute screen capture walking through:
  - User runs `/access-request` in Slack
  - Modal opens, fills form
  - Zendesk ticket created
  - Manager gets approval DM in Slack
  - Manager approves
  - User gets Okta group assignment
  - Final Zendesk ticket showing full audit trail
- [ ] Post to unlisted YouTube. Add link to README

#### 5.5 Portfolio polish (Weekend)
- [ ] Update root `README.md` as the interview landing page. Top section should be a 3-paragraph elevator pitch mapping the repo to Netflix JD bullets
- [ ] Ensure all `public-docs/*.md` files are coherent and cross-linked
- [ ] Add a `public-docs/00-interview-walkthrough.md` — a suggested 15-minute tour of the repo for a technical interview
- [ ] Push everything to GitHub public. Verify the repo renders correctly

### Exit criteria for Phase 5
- `/access-request` Slack command works end-to-end
- Approval flow runs through Workato, grants Okta access on approval
- Demo video recorded and linked
- Root README is interview-ready
- All public docs cross-linked and coherent

---

## Repository Structure After Completion

```
scripts/
  auth0/                    # Historical, not maintained
  okta/                     # New — user provisioning, group rules helpers
    generate_users.py
    provision_users.py
    test_connection.py
  gws/                      # Existing, extended
  slack/                    # New
    provision_user.py
    access_request_bot.py
  zendesk/                  # New
    provision_agent.py
    create_audit_ticket.py
  lifecycle/                # Core of the project
    joiner.py
    mover.py
    leaver.py
    sync_okta_all.py        # Drift detection across all systems
  reports/
    access_request_report.py
workato/
  recipes/
    joiner.json
    access_request_approval.json
okta-workflows/
  joiner.json
.github/workflows/
  drift-detection.yml
public-docs/
  01-auth0-identity-platform.md    # Historical
  02-aws-saml-federation.md        # Existing
  03-gws-federation-and-administration.md  # Existing
  04-okta-migration.md             # New — Phase 1
  05-jml-architecture.md           # New — Phase 3
  06-orchestration-comparison.md   # New — Phase 4
  00-interview-walkthrough.md      # New — Phase 5
  images/
    workato-joiner-recipe.png
    okta-workflows-joiner.png
```

---

## Netflix JD Requirement → Phase Mapping

| JD Requirement | Phase |
|---|---|
| Administer Google Workspace, Slack, Zendesk | 1, 2, 3 |
| Develop, test, deploy API integrations | 2, 3, 5 |
| Low-code/no-code platforms (Workato, Okta Workflows) | 4 |
| Reducing operational overhead, eliminating manual tasks | 2, 3, 5 |
| Identity and access concepts (RBAC, SCIM, SAML, OAuth) | 1, 2, 5 |
| Monitoring and alerting systems | 3 |
| Self-service tools for Support teams | 5 |
| Incident management and response | 3 (drift detection), 5 (audit trail) |
| Generative AI tools (Claude Code, MCP) | 1 (Zendesk MCP), ongoing |

---

## Phase Status Tracker

Update this table at the end of each phase. Commit the update.

| Phase | Weeks | Status | Completion Date | Notes |
|-------|-------|--------|-----------------|-------|
| 1. Okta + Zendesk Foundations | 1 | Not Started | | |
| 2. Python Joiner (Okta → GWS → Slack) | 2 | Not Started | | |
| 3. Zendesk Integration + Mover + Leaver | 3 | Not Started | | |
| 4. Workato Port + Okta Workflows Comparison | 4 | Not Started | | |
| 5. Self-Service Slack Bot + Polish | 5 | Not Started | | |

---

## For Claude Code: Per-Session Prompting

When you start a new Claude Code session on this project, open with a prompt like:

> "I'm working on Phase [N] of the JML Orchestration project. Read `JML_IMPLEMENTATION_GUIDE.md` and `CLAUDE.md`, check the Phase Status Tracker, and tell me which tasks from Phase [N] are next. Follow all ADRs. Before writing any code that touches a SaaS system, show me the plan and wait for confirmation."

This keeps Claude Code aligned with the architectural decisions and prevents scope creep.
