# IT Operations Sandbox

An enterprise SaaS platform engineering lab built around a mock 100-person company ("NovaTech Solutions"). Demonstrates identity federation, cross-platform provisioning, RBAC, security policy automation, and drift detection across **Okta, Google Workspace, Slack, Zendesk, and AWS** — all driven by Python against SaaS APIs, plus MCP-integrated AI operations.

## Why This Project Exists

Modern IT engineering means going beyond admin consoles. This project replicates the systems and workflows of an Enterprise SaaS Platform Engineer: tenant-wide architecture for collaboration platforms, SSO/SCIM from the application side, per-OU security policies, and platform configuration as code.

Every script in this repo solves a problem that couldn't be solved by clicking through a console.

## Identity Platform Migration: Auth0 → Okta

The project originally ran on Auth0 as the IdP; the full Auth0 implementation (100 users, 10 roles, Resource Server with 30 permissions, SAML federation to AWS + GWS, post-login Actions) is preserved on the [`auth0_sandbox`](../../tree/auth0_sandbox) branch as a working snapshot. **Okta is now the primary IdP on `main`**, with a config-as-code RBAC foundation already shipped:

- 3 custom profile attributes (plus `department` / `costCenter` from Okta's base schema)
- 10 department groups — naming aligned to GWS OUs and future SAML attribute values
- 10 active group rules driving automatic department-based membership
- Idempotent Python export/reconcile pipeline (`scripts/okta/`) with audit / dry-run / apply modes
- Okta MCP server connected to Claude Code for interactive administration

Migration rationale and the full Okta-era JML build plan live in [`okta_workato_zendesk_slack.md`](okta_workato_zendesk_slack.md).

## What's Built

> Detailed write-ups: [Auth0 Identity Platform](public-docs/01-auth0-identity-platform.md) | [AWS SAML Federation](public-docs/02-aws-saml-federation.md) | [GWS Federation & Administration](public-docs/03-gws-federation-and-administration.md) | [Okta Migration](public-docs/04-okta-migration.md) | [Slack SCIM Lifecycle](public-docs/05-slack-scim-lifecycle.md) | [Reconcile reports](public-docs/reports/)

### Okta RBAC Foundation (config-as-code)

Department-based RBAC skeleton that every downstream JML target (GWS, Slack, Zendesk, AWS) will plug into. Source of truth is `config/okta/desired-state.json`; all changes land via `scripts/okta/reconcile_config.py --apply`.

```bash
python scripts/okta/export_config.py                    # live tenant → desired-state.json
python scripts/okta/reconcile_config.py                 # audit drift (default mode)
python scripts/okta/reconcile_config.py --apply --dry-run  # preview writes
python scripts/okta/reconcile_config.py --apply         # converge + emit markdown report
```

Brownfield-safe: the reconcile tool is additive-only (no deletes), pattern was validated by manually creating 2 of the 10 groups + 2 of the 10 rules in the UI first, then letting the script create the remaining 8 + 8 without colliding with the hand-seeded state.

- **Profile attributes**: `role_title`, `managerEmail`, `startDate` (base `department` + `costCenter` reused)
- **Groups**: Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing
- **Group rules**: `user.department == "{Department}"` → auto-assign to matching group (fail-closed)
- **App→group assignments** (new): `appAssignments` block round-trips through export/reconcile, captured Okta UI clicks as code

### Okta User Provisioning + Federation

8 NovaTech seed users provisioned across Engineering/Product/IT-Ops/Data via `scripts/okta/provision_users.py` (idempotent skip-if-exists, gitignored credentials file). Group rules auto-assigned each user to their department group within ~30s. Okta → GWS SAML federation working end-to-end via the OIN `*Override` API pattern (admin console hides these fields; the API is the canonical source). Disposable test user `test-jml-01@ohmgym.com` proves the SAML+SCIM plumbing without touching the super-admin account. ([changelog](public-docs/04-okta-migration.md))

- **8-user seed** — `config/okta/okta_seed_users.json`, hand-maintained, mirrors `gws_provision_subset.json` shape, respects Okta + Slack tier caps
- **Three SAML config issues** hit + resolved (SWA→SAML mode, IdP Entity ID mismatch, Audience/ACS override via API) — documented for future operators
- **`apply_slack_saml_overrides.py`** — reusable CLI for the same `*Override` pattern, applied to the Slack OIN app (different SP, same mechanism)

### Slack SCIM Lifecycle

Okta-managed SCIM proven both directions to Slack Enterprise Grid sandbox: provisioning on group assign, deactivation on group unassign, **reactivation** of existing identities (preserves DM history, channel memberships, audit trail) on re-assign. Two trigger surfaces share the same SCIM channel — UI for the analyst-friendly flow, config-as-code (`appAssignments` reconciler) for the engineer-grade flow with drift detection. ([changelog](public-docs/05-slack-scim-lifecycle.md))

```bash
python scripts/slack/audit_log_query.py --action user_created --since 5m
python scripts/slack/audit_log_query.py --action user_deactivated --since 5m
```

- **Slack Audit Logs API foundation** — `scripts/slack/_client.py` handles xoxp- token auth, the `{ok:false}` error envelope, 429 retry, cursor pagination, dual base URLs (Web API + Audit API)
- **Seat-cap diagnosis** — Slack Developer Sandbox 8-active-user cap surfaces as HTTP 500 `user_creation_failed`; diagnosed by counting active users in the audit log (Slack admin UI lags by minutes)
- **SAML still broken** (`sso_failed=1`) — parked; SCIM works around it, Phase 6+ revisits with HAR capture or Slack Support

### Identity Federation (Auth0 → AWS + Google Workspace) — preserved

Auth0 serves as the original SAML 2.0 Identity Provider, federating into both AWS IAM Identity Center and Google Cloud Identity. Post-login Actions dynamically inject department-based SAML attributes into assertions. This federation is live on the `auth0_sandbox` branch; the Okta-side equivalent is planned for a follow-on phase. ([details](public-docs/02-aws-saml-federation.md))

- **Auth0 → AWS**: Department-based Permission Set assignment via SAML attributes
- **Auth0 → GWS**: Per-profile SAML federation with all 10 department OUs assigned SSO profiles
- **SAML troubleshooting**: Diagnosed and resolved audience mismatches on both AWS and GWS federations by inspecting IdP-side logs and assertion formats

### Auth0 RBAC with Resource Server — preserved

Full RBAC chain: **Users → Roles → Permissions → Resource Server**. 30 permissions assigned across 10 roles following least-privilege principles. ([permission matrix](public-docs/01-auth0-identity-platform.md#resource-server--permission-to-role-assignment))

- Resource Server: "NovaTech Internal API" with 30 scoped permissions
- Least-privilege design: no role gets `access:production` by default; `it-admin` gets `manage:*` but not `write:databases`
- Verification: script queries Management API and compares actual permissions against desired matrix — 10 roles, 50 assignments, 0 drift

### Google Workspace Tenant Architecture

Full OU structure mirroring NovaTech's 10 departments in Google Cloud Identity Free, per-OU security policies, Python automation via the Admin SDK, and config-as-code pipeline identical in shape to the Okta one. ([full details](public-docs/03-gws-federation-and-administration.md))

- **10 department OUs** — 2 created manually (console familiarity), 8 via Python Directory API
- **Per-OU 2-Step Verification** — Enforced for IT-Ops, Executive, Finance, HR; allowed for others
- **Per-OU third-party app governance** — Blocked for Finance, HR, Executive; inherited for others
- **User provisioning** — Directory API with department metadata, manager relationships, cost center attributes
- **Security policy audit + drift detection** — `scripts/gws/reconcile_config.py` (same API surface as `scripts/okta/reconcile_config.py`)
- **Cloud Identity Policy API** — Systematically tested and documented Free-edition limitations, repurposed scripts as policy audit tools

### Cross-Platform Drift Detection

Sync engine that uses the IdP as source of truth and detects drift across downstream platforms. The Auth0 era (`sync_auth0_gws.py`) is preserved on `auth0_sandbox`; the Okta-era foundation now exists implicitly in `reconcile_config.py` (which detects drift on app→group assignments across all OIN apps). A unified `sync_okta_all.py` covering GWS + Slack + Zendesk simultaneously is the Phase 7 deliverable.

```bash
python scripts/okta/reconcile_config.py             # drift across attrs, groups, rules, app assignments
python scripts/lifecycle/sync_auth0_gws.py --report  # Auth0-era cross-platform drift (preserved)
```

### User Lifecycle Automation — Joiner + Mover live, Leaver next

`scripts/lifecycle/joiner_workflow.py` orchestrates Okta user creation → group rules fire → SCIM push to Slack/GWS → audit post. `scripts/lifecycle/mover_workflow.py` handles department transfers: Okta attribute update → group rules re-fire → GWS OU move + Slack DM to new manager + audit post. Both write structured JSON logs to gitignored `logs/` for replay. Leaver flow is the next step (also unblocks Slack seat-cap pressure by deactivating obsolete demo accounts). The full JML design is specified in [`okta_workato_zendesk_slack.md`](okta_workato_zendesk_slack.md).

### Email Domain Migration

Migrated 100 Auth0 users from one domain to another via the Management API — updating emails, `user_metadata.manager_email` references, and downstream AWS Identity Store users. ([script details](public-docs/01-auth0-identity-platform.md#email-domain-migration))

## Architecture

```
                    ┌──────────────────────────┐
                    │      Okta Tenant          │  ← primary IdP (main branch)
                    │  API Services app          │
                    │  Private Key JWT client    │
                    │  10 dept groups + rules    │
                    └────────────┬──────────────┘
                                 │
               SAML federation + SCIM provisioning
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
    ┌────▼──────┐      ┌────────▼────────┐     ┌────────▼────────┐
    │ AWS IAM   │      │ Google Cloud    │     │ Slack Enterprise│
    │ Identity  │      │ Identity Free   │     │ Grid Sandbox    │
    │ Center    │      │                 │     │                 │
    │ (deferred)│      │ SAML ✅          │     │ SAML ❌ parked   │
    │           │      │ SCIM ✅          │     │ SCIM ✅ live     │
    │ 3 Perm    │      │ 10 dept OUs     │     │ Audit Logs API  │
    │ Sets      │      │ Per-OU 2SV      │     │ Channel gov.    │
    └───────────┘      └────────┬────────┘     └─────────────────┘
                                │
                    ┌───────────▼───────────────────┐
                    │   Python + MCP Automation      │
                    │   scripts/{okta,gws,lifecycle} │
                    │   Export → desired-state.json  │
                    │   Reconcile w/ audit/apply     │
                    └───────────────────────────────┘

                    ┌──────────────────────────┐
                    │  Auth0 Tenant (historical)│  ← preserved on auth0_sandbox branch
                    │  100 users · 10 roles     │
                    │  SAML 2.0 live to AWS+GWS │
                    └──────────────────────────┘
```

## Mock Company: NovaTech Solutions

100 employees across 10 departments. Department drives everything downstream — GWS OU placement, AWS Permission Set, 2SV posture, future Slack user groups.

| Department | Headcount | Okta Group | Auth0 Role (preserved) | AWS Permission Set | GWS 2SV Policy |
|---|---|---|---|---|---|
| Engineering | 30 | `Engineering` | `engineer` | PowerUser | Allow |
| Sales | 15 | `Sales` | `sales` | ReadOnly | Allow |
| Data | 10 | `Data` | `data-engineer` | PowerUser | Allow |
| Marketing | 10 | `Marketing` | `marketing` | ReadOnly | Allow |
| Product | 8 | `Product` | `product` | ReadOnly | Allow |
| Executive | 7 | `Executive` | `executive` | ReadOnly | **Enforce** |
| IT-Ops | 5 | `IT-Ops` | `it-admin` | Admin | **Enforce** |
| Finance | 5 | `Finance` | `finance` | ReadOnly | **Enforce** |
| Design | 5 | `Design` | `designer` | ReadOnly | Allow |
| HR | 5 | `HR` | `hr` | ReadOnly | **Enforce** |

User metadata contract (preserved across Auth0 → Okta): `{ department, role_title, cost_center, manager_email, start_date }`

**Sandbox user caps:** Okta Integrator Free = 10, Slack Developer = 8, GWS Cloud Identity Free ≈ 10. The user-provisioning phase will pick 5–8 representative users across 3–4 departments rather than replicating all 100.

## Key Scripts

| Script | What It Does |
|---|---|
| `scripts/okta/test_connection.py` | Smoke-test Okta API creds; prints granted scopes |
| `scripts/okta/export_config.py` | Live Okta tenant → `config/okta/desired-state.json` (now exports `appAssignments` + preserves hand-maintained keys) |
| `scripts/okta/reconcile_config.py` | Audit / dry-run / apply drift across schema, groups, group rules, **and app→group assignments**; emits markdown report |
| `scripts/okta/provision_users.py` | Batch-create the 8-user NovaTech seed across 4 departments; idempotent skip-if-exists; gitignored creds file |
| `scripts/okta/apply_slack_saml_overrides.py` | One-purpose CLI that PUTs the four `*Override` SAML fields on the Slack OIN app (the API-only escape hatch documented in `04-okta-migration.md` §"Issue 3") |
| `scripts/okta/_client.py` | Private Key JWT auth helper (shared by all Okta scripts; same creds as MCP server) |
| `scripts/slack/_client.py` · `_post.py` · `audit_log_query.py` · `test_connection.py` | Slack API foundation: GET/POST helpers with `{ok:false}` envelope handling, Audit Logs API CLI for SCIM/SAML diagnostics |
| `scripts/lifecycle/joiner_workflow.py` | End-to-end Joiner: Okta create → group rules fire → SCIM push to GWS+Slack → audit post |
| `scripts/lifecycle/mover_workflow.py` | Department change → Okta attr update → group rules re-fire → GWS OU move + Slack DM/audit |
| `scripts/gws/export_config.py` · `reconcile_config.py` | GWS equivalent — same pattern, same flags |
| `scripts/gws/create_ous.py` · `provision_users.py` · `configure_2sv.py` | Directory API automation + 2SV policy audit |
| `scripts/lifecycle/sync_auth0_gws.py` | Cross-platform drift detection: Auth0 departments vs. GWS OU placement |
| `scripts/auth0/provision_users.py` · `assign_role_permissions.py` · `update_user_emails.py` | Preserved Auth0 automation (main branch + `auth0_sandbox`) |
| `scripts/auth0/actions/*.js` | Preserved Auth0 Actions: department → AWS Permission Set + GWS attribute injection |

All scripts support `--dry-run` for safe change management and are idempotent (safe to re-run).

## Technical Decisions & Tradeoffs

**Why migrate from Auth0 to Okta?** Auth0 is Okta-owned but has diverging product surface. The target role is Okta-native, and the JML project design leans on Workato + Okta Workflows + Okta's built-in group rules — concepts with no 1:1 Auth0 equivalent. Auth0 remains preserved on the `auth0_sandbox` branch so the SAML federation + Resource Server work is still demoable.

**Why config-as-code (Python, not Terraform) for Okta?** Matches the existing `scripts/gws/` pattern exactly (export → desired-state.json → reconcile with audit/apply/dry-run). No new toolchain. The Okta Terraform provider is solid but would force a two-system split between script-managed users and HCL-managed groups; the repo stays consistent with one language driving all SaaS APIs.

**Why Google Cloud Identity Free?** Full Admin Console, Directory API, and OU management without a paid Workspace license. The Cloud Identity Policy API is read-only on the Free edition (v1beta1 `create` returns 500, `patch` returns 400) — discovered through systematic API testing, documented, and worked around by using the Admin Console for writes and the API for audit/drift detection.

**Why Python against SaaS APIs?** Every automation calls APIs directly — Okta Management API, Auth0 Management API, Google Admin SDK, Cloud Identity Policy API, AWS CLI. No GUI clicks recorded as "automation." Scripts are the deployment artifact.

## Project Structure

```
scripts/
  okta/                            # Okta Management API — RBAC config-as-code
    _client.py                     #   Shared Private Key JWT auth helper
    test_connection.py             #   Creds + scope smoke test
    export_config.py               #   Live tenant → desired-state.json (incl. appAssignments)
    reconcile_config.py            #   Audit / apply / dry-run drift across attrs, groups, rules, app assignments
    provision_users.py             #   Batch user creation from config/okta/okta_seed_users.json
    apply_slack_saml_overrides.py  #   PUT the 4 *Override SAML fields on the Slack OIN app (API-only)
  slack/                           # Slack Web + Audit Logs API foundation
    _client.py                     #   xoxp- token, {ok:false} envelope, cursor pagination
    _post.py                       #   POST helpers (chat.postMessage, conversations.open)
    test_connection.py             #   Auth + auditlogs:read smoke test
    audit_log_query.py             #   Slack Enterprise Audit Logs CLI (SCIM/SAML observability)
  auth0/                           # Preserved Auth0 Management API automation
    generate_users.py  provision_users.py  update_user_emails.py
    assign_role_permissions.py
    actions/                       #   Auth0 post-login Actions (Node.js)
      aws-saml-attribute-mapping.js
      gws-saml-attribute-mapping.js
  gws/                             # Google Workspace Admin SDK automation
    export_config.py  reconcile_config.py
    create_ous.py  provision_users.py  configure_2sv.py
    audit_apps.py  audit_sharing.py  audit_policies.py  manage_groups.py
  lifecycle/                       # Cross-platform identity automation
    sync_auth0_gws.py              #   Auth0 → GWS drift detection + remediation
    joiner_workflow.py             #   End-to-end Joiner: Okta create → SCIM → audit post
    mover_workflow.py              #   Dept change: Okta attr → group rules → GWS OU + Slack DM
config/
  okta/desired-state.json          # Okta RBAC source of truth (groups, rules, attrs, app assignments)
  okta/okta_seed_users.json        # 8 NovaTech seed users across Engineering/Product/IT-Ops/Data
  gws/desired-state.json           # GWS source of truth (OUs, users, groups, policies)
public-docs/
  01-auth0-identity-platform.md
  02-aws-saml-federation.md
  03-gws-federation-and-administration.md
  04-okta-migration.md             # Okta → GWS federation changelog incl. *Override pattern
  05-slack-scim-lifecycle.md       # Okta → Slack SCIM lifecycle (provision/deprovision/reactivate)
  reports/                         # Auto-generated reconcile reports (demoable)
terraform/
  auth0/                           # Auth0 tenant-as-code (planned)
  aws/                             # AWS infrastructure (planned)
```

## Documentation

Detailed write-ups covering architecture, troubleshooting, and technical decisions:

| Document | Covers |
|---|---|
| [Auth0 Identity Platform](public-docs/01-auth0-identity-platform.md) | Tenant setup, 100-user provisioning, RBAC architecture, email domain migration, Auth0 Actions, Okta concept mapping |
| [AWS SAML Federation](public-docs/02-aws-saml-federation.md) | SAML 2.0 architecture, Permission Sets, attribute mapping, troubleshooting (audience + NameID mismatches), debugging methodology |
| [GWS Federation & Administration](public-docs/03-gws-federation-and-administration.md) | Cloud Identity setup, OU architecture, SAML federation, per-OU 2SV + app governance, drift detection, policy audit, API limitation discovery |
| [Okta Migration](public-docs/04-okta-migration.md) | Okta → GWS federation test changelog: SAML+SCIM end-to-end via test user, three SAML config issues hit + resolved, the OIN `*Override` API pattern |
| [Slack SCIM Lifecycle](public-docs/05-slack-scim-lifecycle.md) | Okta → Slack SCIM provisioning/deprovisioning/reactivation proven both directions; UI-vs-CaC dual mechanism; 8-user seat-cap diagnosis from audit logs |
| [Okta JML Build Plan](okta_workato_zendesk_slack.md) | Okta-era Joiner/Mover/Leaver design across GWS + Slack + Zendesk with Python / Workato / Okta Workflows implementations |
| [Okta RBAC Foundation reports](public-docs/reports/) | Auto-generated reconcile reports showing zero-drift state + remediation history |

## Roadmap

### Progress at a glance

**4 complete · 2 partial · 3 planned** — identity layer + provisioning + downstream SCIM all proven on real test users. Slack SAML is the one remaining blocker; SCIM works around it.

### Most recent milestone

**Phase 5 partial — Slack SCIM Lifecycle (shipped):** end-to-end Okta → Slack SCIM provisioning proven via both UI assignment and config-as-code (`appAssignments` reconciler). Deprovisioning, reactivation (with audit-trail preservation), and 8-user seat-cap behavior all observed and documented in [`public-docs/05-slack-scim-lifecycle.md`](public-docs/05-slack-scim-lifecycle.md). Slack Audit Logs API foundation (`scripts/slack/`) provides the observability layer. Slack SAML still failing at `sso_failed=1` — parked; SCIM is independent.

### Next up

**Phase 6 — Zendesk Integration**, or finish Phase 5 by getting Slack SAML over the line. Phase 4 is functionally complete (8-user seed provisioned, Okta → GWS federation working with the `*Override` pattern, AWS deferred). Phase 3.4 Leaver flow is the natural unblocker for the seat-cap pressure on Slack.

### Full phase tracker

| # | Phase | Focus | Status |
|---|---|---|---|
| 1 | Auth0 Foundation | Tenant, RBAC, SAML → AWS + GWS, post-login Actions | ✅ Complete — preserved on [`auth0_sandbox`](../../tree/auth0_sandbox) |
| 2 | Google Workspace Architecture | OU hierarchy, per-OU 2SV + app governance, `reconcile_config.py` | ✅ Complete |
| 3 | Okta RBAC Foundation | Profile schema, dept groups, group rules, config-as-code pipeline | ✅ Complete |
| 4 | Okta User Provisioning + Federation | 8 seed users · Okta → GWS SAML (`*Override` pattern) · Okta → AWS deferred | ✅ Complete (AWS deferred) |
| 5 | Slack Platform Engineering | SCIM provisioning, audit-log observability, **SAML still broken** | 🚧 **Partial (current)** — SCIM ✅, SAML ❌ |
| 6 | Zendesk Integration | Ticket forms, API token, MCP server, JML audit-trail tickets | ⏳ Planned |
| 7 | Cross-Platform Identity | `sync_okta_all.py` drift detection across all JML targets | ⏳ Planned |
| 8 | Config-as-Code & AI Ops | CI/CD for tenant configs, Claude MCP workflows, escalation runbooks | 🚧 Partial — Okta + Auth0 + Slack APIs scripted; MCP connected |

### How the phases map to the Enterprise SaaS Engineer JD

- **Phases 1–3** establish the identity layer: RBAC model, attribute-driven group membership, federation primitives.
- **Phase 4** is the bridge — users + SAML unlock every downstream integration.
- **Phases 5–6** prove the JML story on the two platforms the role names most often (Slack, Zendesk).
- **Phase 7** is the drift-detection / compliance story: one sync engine comparing desired state across all four SaaS tenants.
- **Phase 8** wraps the project in the "platform config as code with AI ops" framing: CI gates, MCP-driven operations, runbooks.

## Identity Protocol Reference

| Concept | Auth0 (preserved) | Okta (active) |
|---|---|---|
| User Store | `user_metadata` + `app_metadata` | Universal Directory + custom profile attributes |
| Automation | Actions (Node.js serverless) | Workflows (visual builder) + Hooks |
| Provisioning | Management API + webhooks | SCIM to connected apps + Management API |
| SSO Federation | SAML/OIDC connections | SAML/OIDC app integrations (many pre-built via OIN) |
| MFA | Guardian, adaptive MFA | Okta Verify, FastPass |
| Groups/Roles | Roles + Permissions + Organizations | Groups + Group Rules (attribute-driven) |
| Logs/Audit | Logs + Log Streams | System Log + Event Hooks |
| IaC | Terraform Provider | Terraform Provider + config-as-code scripts |

## License

MIT
