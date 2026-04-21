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

> Detailed write-ups: [Auth0 Identity Platform](public-docs/01-auth0-identity-platform.md) | [AWS SAML Federation](public-docs/02-aws-saml-federation.md) | [GWS Federation & Administration](public-docs/03-gws-federation-and-administration.md) | [Okta RBAC Foundation Report](public-docs/reports/)

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

Sync engine that uses the IdP (currently Auth0) as source of truth and detects drift across Google Workspace. An Okta-sourced equivalent (`sync_okta_gws.py`) is the next step once Okta user provisioning is live.

```bash
python scripts/lifecycle/sync_auth0_gws.py --admin-email admin@domain.com --report
```

Detects four categories: OU mismatches (auto-remediated), missing-from-GWS, orphaned-in-GWS, unknown-department.

### User Lifecycle Automation — Auth0 era preserved; Okta-era next phase

Python scripts for the full Joiner/Mover/Leaver lifecycle across Auth0 and Google Workspace. The Okta-era JML design (including Zendesk as the audit trail + agent-seat provisioning target) is specified in [`okta_workato_zendesk_slack.md`](okta_workato_zendesk_slack.md) and will be built against the RBAC foundation above. ([Auth0 provisioning details](public-docs/01-auth0-identity-platform.md))

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
               (future: SAML/OIDC federation)
                                 │
         ┌───────────────────────┼───────────────────────┐
         │                       │                       │
    ┌────▼──────┐      ┌────────▼────────┐     ┌────────▼────────┐
    │ AWS IAM   │      │ Google Cloud    │     │ Slack Developer │
    │ Identity  │      │ Identity Free   │     │ Sandbox         │
    │ Center    │      │                 │     │                 │
    │           │      │ 10 dept OUs     │     │ Admin API       │
    │ 3 Perm    │      │ Per-OU 2SV      │     │ SCIM            │
    │ Sets      │      │ SSO profiles    │     │ Channel gov.    │
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
| `scripts/okta/export_config.py` | Live Okta tenant → `config/okta/desired-state.json` (with `.tmp` write + clobber guard) |
| `scripts/okta/reconcile_config.py` | Audit / dry-run / apply drift; emits markdown report to `public-docs/reports/` |
| `scripts/okta/_client.py` | Private Key JWT auth helper (shared by all Okta scripts; same creds as MCP server) |
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
    export_config.py               #   Live tenant → desired-state.json
    reconcile_config.py            #   Audit / apply / dry-run drift reconciliation
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
config/
  okta/desired-state.json          # Okta RBAC source of truth (groups, rules, attrs)
  gws/desired-state.json           # GWS source of truth (OUs, users, groups, policies)
public-docs/
  01-auth0-identity-platform.md
  02-aws-saml-federation.md
  03-gws-federation-and-administration.md
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
| [Okta JML Build Plan](okta_workato_zendesk_slack.md) | Okta-era Joiner/Mover/Leaver design across GWS + Slack + Zendesk with Python / Workato / Okta Workflows implementations |
| [Okta RBAC Foundation reports](public-docs/reports/) | Auto-generated reconcile reports showing zero-drift state + remediation history |

## Roadmap

### Progress at a glance

**3 complete · 1 partial · 4 planned** — the identity-layer foundations are in place; the next cycle shifts from "build the skeleton" to "plug downstream systems into it."

### Most recent milestone

**Phase 3 — Okta RBAC Foundation (shipped):** config-as-code pipeline for 10 department groups, 10 attribute-driven group rules, and 3 custom profile attributes. Round-trip drift test passes at zero. Okta MCP server connected to Claude Code. Demoable report at [`public-docs/reports/`](public-docs/reports/).

### Next up

**Phase 4 — Okta User Provisioning + Federation.** Pick 5–8 representative users across 3–4 departments (respecting the 10-user Okta free-tier cap), build `scripts/okta/provision_users.py` mirroring the Auth0 pattern, then re-federate AWS IAM Identity Center and Google Cloud Identity against Okta. This unblocks everything downstream — group rules can only prove themselves once actual users carry `department` attributes, and SAML federation is the prerequisite for any real JML flow.

### Full phase tracker

| # | Phase | Focus | Status |
|---|---|---|---|
| 1 | Auth0 Foundation | Tenant, RBAC, SAML → AWS + GWS, post-login Actions | ✅ Complete — preserved on [`auth0_sandbox`](../../tree/auth0_sandbox) |
| 2 | Google Workspace Architecture | OU hierarchy, per-OU 2SV + app governance, `reconcile_config.py` | ✅ Complete |
| 3 | Okta RBAC Foundation | Profile schema, dept groups, group rules, config-as-code pipeline | ✅ **Complete (current)** |
| 4 | Okta User Provisioning + Federation | 5–8 test users · Okta → GWS SAML · Okta → AWS SAML | ⏳ Planned — next up |
| 5 | Slack Platform Engineering | SCIM provisioning, channel governance, app management | ⏳ Planned |
| 6 | Zendesk Integration | Ticket forms, API token, MCP server, JML audit-trail tickets | ⏳ Planned |
| 7 | Cross-Platform Identity | `sync_okta_all.py` drift detection across all JML targets | ⏳ Planned |
| 8 | Config-as-Code & AI Ops | CI/CD for tenant configs, Claude MCP workflows, escalation runbooks | 🚧 Partial — Okta + Auth0 MCP servers connected |

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
