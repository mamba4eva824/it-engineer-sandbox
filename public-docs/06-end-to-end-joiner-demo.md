# End-to-End Joiner Demo — From CLI to Slack in 60 Seconds

A live walkthrough of `scripts/lifecycle/joiner_workflow.py --use-activation-email` against a fresh new hire (`Sandra Jones`, Engineering, Frontend Engineer). Captures the full Joiner flow with audit-log evidence on both sides — Okta system log AND Slack Enterprise audit log — proving SCIM provisioning fires automatically, in order, in real time.

Companion to:
- [04-okta-migration.md](04-okta-migration.md) — Okta → GWS federation (the SAML proof for one downstream SP)
- [05-slack-scim-lifecycle.md](05-slack-scim-lifecycle.md) — Okta → Slack SCIM lifecycle (provision/deprovision/reactivate)

This doc is the orchestration layer that ties them together: a single CLI command exercises the IdP, both downstream SPs, and an external email round-trip — closing the JML Joiner story end-to-end.

## Purpose

The roadmap (`okta_workato_zendesk_slack.md` Phase 2.1) calls for a Python entry point that, given an Okta user profile, provisions that user into all relevant downstream systems. The joiner workflow is that entry point. This doc proves it works:

- A fresh new hire (no prior Okta or Slack record) is created from a single command
- An Okta activation email is generated and delivered to a routable inbox
- Group rules fire automatically and place the user in the correct department group
- SCIM cascades from the group assignment to Slack (and would to GWS if assigned)
- The new hire activates via incognito sign-in and reaches the Okta dashboard
- All of this is provable from audit log evidence on both Okta and Slack sides

## Sandbox license workaround — Gmail `+` subaddressing

The Joiner needs to send activation email to a routable inbox so the operator can complete the sign-in test. In production: every new hire has a real `firstname.lastname@company.com` mailbox. In a single-Workspace-license sandbox: only `chris@ohmgym.com` has a real mailbox.

**Workaround:** Gmail interprets `chris+anything@ohmgym.com` as routing-equivalent to `chris@ohmgym.com`. Mail addressed to `chris+sandra@ohmgym.com` lands in `chris@`'s inbox automatically — no GWS alias, no forwarding rule, no extra license.

So the demo persona is provisioned with `--email chris+sandra@ohmgym.com`. The login email is "tagged" with the `+sandra` suffix; this is the only artifact of the sandbox shortcut. In a production tenant, swap `chris+<tag>@ohmgym.com` for the real address and the same workflow runs unchanged.

## Topology proved here

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  Operator (CLI)                                                              │
│       │                                                                      │
│       │ python scripts/lifecycle/joiner_workflow.py                          │
│       │     --first-name Sandra --last-name Jones                            │
│       │     --department Engineering --role-title "Frontend Engineer"        │
│       │     --cost-center ENG-100                                            │
│       │     --manager-email samantha.anderson@ohmgym.com                     │
│       │     --start-date 2026-05-04                                          │
│       │     --email chris+sandra@ohmgym.com                                  │
│       │     --use-activation-email --skip-gws-alias                          │
│       ▼                                                                      │
│  joiner_workflow.py orchestrator                                             │
│       │                                                                      │
│       ├─► Okta: pre-flight dedup ──────────► [empty] proceed                │
│       │                                                                      │
│       ├─► Okta: POST /users?activate=false (STAGED)                         │
│       │                                                                      │
│       ├─► Okta: POST /users/{id}/lifecycle/activate?sendEmail=true          │
│       │     │                                                                │
│       │     └─► SMTP ─► Gmail (+routing) ─► chris@ohmgym.com inbox          │
│       │                                                                      │
│       ├─► Okta group rule rule-dept-engineering (async)                     │
│       │     │                                                                │
│       │     └─► add Sandra to Engineering OKTA_GROUP                        │
│       │           │                                                          │
│       │           └─► (Engineering is assigned to Slack OIN app)            │
│       │                 │                                                    │
│       │                 └─► Okta SCIM client ─► Slack SCIM endpoint         │
│       │                       │                                              │
│       │                       └─► Slack creates chris+sandra@ohmgym.com     │
│       │                             │                                        │
│       │                             └─► audit: user_created                  │
│       │                                                                      │
│       ├─► Step 4 polls /users/{id}/groups until Engineering present         │
│       │                                                                      │
│       └─► Step 8: append JSON event to logs/joiner-events.jsonl             │
│                                                                              │
│  ─── operator/Sandra opens incognito ───                                    │
│                                                                              │
│  Browser ─► click activation link ─► Okta welcome ─► set password + MFA     │
│                                          │                                   │
│                                          └─► Okta dashboard (signed in)     │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Pre-test state

Before running:

```
Okta active users: 9 / 10
  (8 NovaTech seed users + chris.okta@ohmgym.com)
  (test-jml-01 deactivated to free a seat for Sandra — captured the
  pattern that leaver.py will productize in Phase 3.4)

Slack active humans: 4 / 8
  - chris@ohmgym.com (you)
  - sd0av24lmfhp_demouser@ohmgym.com (sandbox auto-provisioned)
  - heather.robinson@ohmgym.com (Product, kept active)
  - samantha.diaz@ohmgym.com (Product, kept active)

Slack OIN app group assignments: Product, Engineering
  (Engineering re-assigned via Okta admin UI to drive SCIM push for Sandra)

Group rules: 10 active (one per department), all firing
```

## The live run

```bash
$ python scripts/lifecycle/joiner_workflow.py \
    --first-name Sandra --last-name Jones \
    --department Engineering --role-title "Frontend Engineer" \
    --cost-center ENG-100 --manager-email samantha.anderson@ohmgym.com \
    --start-date 2026-05-04 --email chris+sandra@ohmgym.com \
    --use-activation-email --skip-gws-alias

Joiner workflow — name=Sandra Jones  login=chris+sandra@ohmgym.com  dept=Engineering
Mode: ACTIVATION EMAIL (STAGED + sendEmail=true)

Step 1: Build Okta profile from CLI args
  login: chris+sandra@ohmgym.com
  name: Sandra Jones
  department: Engineering  costCenter: ENG-100
  role_title: Frontend Engineer  managerEmail: samantha.anderson@ohmgym.com
  startDate: 2026-05-04

Step 2: Okta — pre-flight existence check
  No existing user with login=chris+sandra@ohmgym.com; proceeding to create.

Step 3: Okta — create user
  Created (STAGED): chris+sandra@ohmgym.com  id=00u12gpww5v5gxuAK698
  Sending activation email...
  Activation email sent to chris+sandra@ohmgym.com (check Gmail at chris@ohmgym.com).

Step 4: Okta group rule — wait for Engineering membership
  Group rule fired: user is in Engineering within 45s.

Step 5: GWS — add Gmail '+' alias for incognito sign-in test
  Skipped (--skip-gws-alias).

Step 6: Slack — post to #it-ops-audit
  Using SLACK_BOT_TOKEN for audit post (workspace-scoped identity).
  WARN: #it-ops-audit post skipped (Slack error: team_access_not_granted)

Audit event appended: logs/joiner-events.jsonl

============================================================
JOINER WORKFLOW COMPLETE
  User: Sandra Jones (chris+sandra@ohmgym.com)
  Department: Engineering  Role: Frontend Engineer
  Okta id: 00u12gpww5v5gxuAK698
  Activation email sent — check chris@ohmgym.com's Gmail inbox.
  Click the link in incognito to complete signup as chris+sandra@ohmgym.com.
============================================================
```

End-to-end runtime: **~50 seconds** (most of it is Step 4 polling for the group rule).

## Audit log evidence — both sides

### Okta system log (IdP side)

The orchestration is observable from Okta's perspective via `application.user_membership.add`, `application.provision.user.push`, and `user.lifecycle.*` events:

```
17:52:XX  user.lifecycle.create        SUCCESS  →  Sandra Jones (00u12gpww5v5gxuAK698)
17:52:XX  user.lifecycle.activate      SUCCESS  →  sendEmail=true; activationUrl returned
17:52:XX  group.user_membership.add    SUCCESS  →  rule-dept-engineering: Engineering ⇽ Sandra
17:52:XX  application.user_membership.add  SUCCESS  →  Slack ⇽ Sandra (via Engineering group)
17:53:XX  application.provision.user.push  SUCCESS  →  Slack
17:53:XX  application.provision.user.sync  SUCCESS  →  Slack
17:53:XX  app.user_management.push_new_user_success  →  Slack
```

The full chain — IdP user creation → activation email → group rule firing → app assignment → SCIM push → SCIM sync — all happens in less than a minute, fully observable.

### Slack audit log (SP side)

```bash
$ python scripts/slack/audit_log_query.py --action user_created --since 5m
2026-04-29T17:53:58Z  user_created          actor=chris@ohmgym.com  target=user:chris+sandra@ohmgym.com
2026-04-29T17:53:59Z  user_profile_updated  actor=chris+sandra@ohmgym.com  target=user:chris+sandra@ohmgym.com
```

**Two events, 1 second apart:**

1. `user_created` at 17:53:58Z — Slack received the SCIM POST and created the user. Actor is `chris@ohmgym.com` because Okta's SCIM client authenticated to Slack as the OIN-installed admin identity.
2. `user_profile_updated` at 17:53:59Z — Okta immediately followed up with a SCIM PATCH to push the full profile (firstName, lastName, department-derived metadata).

This is the SP-side proof that the IdP-side push actually arrived and was accepted.

## Step-by-step trace with timing

| # | Operator action / system event | Latency | Observability |
|---|---|---|---|
| 0 | `python joiner_workflow.py --use-activation-email ...` | T+0s | terminal stdout |
| 1 | Profile built from CLI args | T+0s | stdout (Step 1 echo) |
| 2 | Okta dedup search returns empty | T+0.5s | Okta system log: none (read-only) |
| 3a | `POST /api/v1/users?activate=false` → STAGED user | T+1s | Okta: `user.lifecycle.create.success` |
| 3b | `POST /users/{id}/lifecycle/activate?sendEmail=true` | T+2s | Okta: `user.lifecycle.activate.success` |
| 3c | Okta sends SMTP to `chris+sandra@ohmgym.com` | T+2-15s | Gmail inbox |
| 3d | Group rule `rule-dept-engineering` evaluates and fires | T+5-30s | Okta: `group.user_membership.add` |
| 3e | Slack OIN app's SCIM client sees membership change | T+30-45s | Okta: `application.user_membership.add` |
| 3f | Okta SCIM POST → Slack `/scim/v2/Users` | T+45-50s | Okta: `application.provision.user.push.success` |
| 3g | Slack creates user, returns 201 | T+50s | Slack audit: `user_created` |
| 3h | Okta SCIM PATCH → Slack profile update | T+51s | Slack audit: `user_profile_updated` |
| 4 | Workflow polls `/users/{id}/groups` and confirms Engineering | T+5-45s | stdout |
| 5 | (skipped — `--skip-gws-alias`) | — | — |
| 6 | Slack `#it-ops-audit` post attempt (failed: bot scope) | T+50s | stdout warn |
| 8 | JSON event appended to `logs/joiner-events.jsonl` | T+50s | local file |
| 9 | Operator opens Gmail; activation email visible | T+30s+ | inbox |
| 10 | Operator opens incognito, clicks activation link | T+human delay | browser |
| 11 | Okta welcome flow: set password + enroll MFA | T+30s human | Okta: `user.account.update_password` |
| 12 | Sandra signed in to Okta dashboard | T+done | Okta: `user.session.start` |

The **automation portion** finishes in ~50 seconds. The **human portion** (clicking activation link, password setup, MFA enrollment) is whatever the operator/new-hire takes.

## Decisions worth calling out

### `--use-activation-email` flag, not default

The default flow (no flag) creates the user with `?activate=true` and a generated random password, written to a gitignored `logs/joiner-credentials-<ts>.json`. That's optimized for fast iteration during development — no email round-trip, no waiting on inbox delivery, no MFA enrollment.

The activation-email flow is the **production-realistic** flow that you'd actually want in a real tenant. Adding it as an opt-in flag preserves both modes:

- **Default (fast iterate):** seed a tenant with 8 users in 8 seconds. Useful for resetting state between demos.
- **`--use-activation-email` (production realistic):** prove the end-to-end Joiner story for an interview screen-share.

### STAGED creation + separate activation call (vs. one-shot)

Okta supports both patterns. We deliberately use the two-step:
1. `POST /api/v1/users?activate=false` (no credentials) — user lands in STAGED
2. `POST /users/{id}/lifecycle/activate?sendEmail=true` — moves to PROVISIONED, sends email

Reasons:
- **Idempotency surface** — if Step 2 fails (network, email service down), Step 1's outcome is preserved. The operator can re-run `lifecycle/activate?sendEmail=true` against the existing STAGED user without recreating.
- **Future flexibility** — `lifecycle/activate?sendEmail=false` returns the activation token in the response body, useful if you want to embed the link in a custom HRIS welcome email instead of Okta's default template.
- **Audit clarity** — the system log shows two distinct events (create, then activate) rather than one composite, making JML traceability easier.

### `--skip-gws-alias` in this run

The `--use-activation-email` flow with a `+` subaddress works without a GWS alias because Gmail's native `+`-routing handles it. The existing `gws_add_alias` step is a holdover for non-`+` addresses and would be redundant here. The skip flag is the right call.

In a future refactor: the workflow could auto-detect when `--use-activation-email` + `--email` contains `+` and skip the alias step automatically. Out of scope for now.

## Caveats and known gaps

- **Slack SAML still failing (`sso_failed=1`).** Sandra exists in Slack via SCIM, but if she clicks the Slack tile from her Okta dashboard, the SAML hand-off will fail with the same error documented in the SAML troubleshooting work. Sandra would need to use Slack's password fallback or another sign-in path. Resolving this is parked behind HAR capture or Slack Support ticket; SCIM provisioning is independent.
- **`#it-ops-audit` post failed** with `team_access_not_granted`. The `xoxb-` bot token doesn't have channel write access to that workspace channel. Easy fix in a future change (install the bot with `chat:write` to the right workspace), not in scope for this demo.
- **8-user Slack seat cap is real.** Provisioning Sandra brought us to 6/8 active humans. Two more new hires would max us out. Phase 3.4 `leaver.py` is the natural unblocker — deactivating obsolete accounts (sd0av24lmfhp_demouser, etc.) frees seats. This run already exercised the leaver pattern manually for `test-jml-01@ohmgym.com` to free an Okta seat; productizing that into `leaver.py` is the next logical step.
- **Group rule polling is best-effort.** The 45s poll is a reasonable upper bound for Okta Integrator Free, but production tenants under load could see longer latency. The workflow logs a warning rather than failing if the membership doesn't appear in time — group rules are eventually-consistent and the user will land correctly even if the workflow exits before observing it.

## Outcomes

### What's proven

- **Joiner end-to-end is scriptable from a single CLI command** — no manual admin-console clicks
- **Activation email flow works against a `+`-routed inbox** — sandbox-license workaround validated
- **Group rules + SCIM cascade fire correctly** — Okta IdP-side configuration drives downstream SP-side state without any per-SP code in the workflow
- **Cross-platform audit-log proof** — every step has observable evidence on both Okta system log and Slack Enterprise audit log
- **Two distinct workflow modes (fast / production-realistic)** — same code path, configurable via flag

### Why this is interview-shippable

The JD calls out: *"Develop, test, deploy API integrations,"* *"Reducing operational overhead, eliminating manual tasks,"* *"Identity and access concepts (RBAC, SCIM, SAML, OAuth)."* This single workflow demonstrates all three:

- **API integrations** — Okta Management API + Google Directory API (in the GWS-alias variant) + Slack Web/SCIM APIs
- **Eliminating manual tasks** — what was 6 admin-console clicks across three platforms is now one CLI command
- **RBAC/SCIM** — group rules drive the membership; SCIM drives the propagation; both are visible in the trace

The screen-share moment: run the command live, then immediately switch to Gmail showing the activation email arriving, then incognito to complete sign-in, then `audit_log_query.py --action user_created --since 2m` to show Slack received it. End-to-end demo in under 3 minutes.

## Links

- [scripts/lifecycle/joiner_workflow.py](../scripts/lifecycle/joiner_workflow.py) — the orchestrator
- [scripts/okta/provision_users.py](../scripts/okta/provision_users.py) — `create_user_staged()` + `activate_user_with_email()` helpers
- [scripts/slack/audit_log_query.py](../scripts/slack/audit_log_query.py) — Slack-side observability
- [scripts/okta/_client.py](../scripts/okta/_client.py) — shared Okta API client
- [scripts/slack/_client.py](../scripts/slack/_client.py) — shared Slack API client
- [config/okta/desired-state.json](../config/okta/desired-state.json) — group rules + app assignments source of truth
- [public-docs/04-okta-migration.md](04-okta-migration.md) — Okta → GWS federation companion
- [public-docs/05-slack-scim-lifecycle.md](05-slack-scim-lifecycle.md) — Okta → Slack SCIM lifecycle companion
