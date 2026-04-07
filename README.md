# IT Operations Sandbox

An enterprise SaaS platform engineering lab built around a mock 100-person company ("NovaTech Solutions"). Demonstrates identity federation, cross-platform provisioning, security policy automation, and drift detection across Auth0, Google Workspace, Slack, and AWS — all driven by Python against SaaS APIs.

## Why This Project Exists

Modern IT engineering means going beyond admin consoles. This project replicates the systems and workflows of an Enterprise SaaS Platform Engineer: tenant-wide architecture for collaboration platforms, SSO/SCIM from the application side, per-OU security policies, and platform configuration as code.

Every script in this repo solves a problem that couldn't be solved by clicking through a console.

## What's Built

### Identity Federation (Auth0 → AWS + Google Workspace)

Auth0 serves as the SAML 2.0 Identity Provider, federating into both AWS IAM Identity Center and Google Cloud Identity. Post-login Actions dynamically inject department-based SAML attributes into assertions — the same pattern used for attribute-based access control in Okta.

```
Auth0 (IdP)
├── SAML 2.0 → AWS IAM Identity Center
│   └── Post-login Action maps department → Permission Set (Admin/PowerUser/ReadOnly)
└── SAML 2.0 → Google Cloud Identity
    └── Per-profile SSO with unique Entity ID + ACS URL per SAML profile
```

- **Auth0 → AWS**: Department-based Permission Set assignment via SAML attributes
- **Auth0 → GWS**: Per-profile SAML federation with all 10 department OUs assigned SSO profiles
- **SAML troubleshooting**: Diagnosed and resolved audience mismatches on both AWS and GWS federations by inspecting IdP-side logs and assertion formats

### Google Workspace Tenant Architecture

Built a full OU structure mirroring NovaTech's 10 departments in Google Cloud Identity Free, with per-OU security policies and Python automation via the Admin SDK.

- **10 department OUs** — 2 created manually (console familiarity), 8 via Python Directory API (automation at scale)
- **Per-OU 2-Step Verification** — Enforced for IT-Ops, Executive, Finance, HR (sensitive access); allowed for others
- **User provisioning** — Python script creates users in correct OUs via Directory API with department metadata, manager relationships, and cost center attributes
- **Cloud Identity Policy API** — Explored v1beta1 write operations, systematically tested and documented API limitations on the Free edition, repurposed scripts as policy audit tools

### Cross-Platform Drift Detection

A sync engine that uses Auth0 as the source of truth and detects drift across Google Workspace.

```bash
python scripts/lifecycle/sync_auth0_gws.py --admin-email admin@domain.com --report
```

Detects four categories of drift:
- **OU mismatches** — user in wrong OU based on Auth0 department (auto-remediates)
- **Missing from GWS** — Auth0 user not provisioned in GWS
- **Orphaned in GWS** — GWS user not in Auth0 directory
- **Unknown department** — Auth0 department doesn't map to any OU

Generates markdown drift reports for compliance documentation.

### User Lifecycle Automation

Python scripts for the full Joiner/Mover/Leaver lifecycle across Auth0 and Google Workspace:

- **Joiner**: Provision user in Auth0 with department metadata → assign RBAC role → create in GWS in correct OU → SAML SSO ready
- **Mover**: Update department in Auth0 → sync script detects drift → moves user to correct GWS OU → role reassignment
- **Leaver**: Block Auth0 account → revoke tokens → remove roles → suspend GWS account

### Email Domain Migration

Migrated 100 Auth0 users from one domain to another via the Management API — updating emails, `user_metadata.manager_email` references, and downstream AWS Identity Store users. Demonstrates the identity reconciliation work involved in tenant consolidation.

## Architecture

```
                    ┌──────────────────────────┐
                    │      Auth0 Tenant         │
                    │    (SAML 2.0 IdP, RBAC)   │
                    │    100 users, 10 roles     │
                    └────────────┬──────────────┘
                                 │
              Post-Login Actions inject SAML
              attributes per Service Provider
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
                    ┌───────────▼───────────┐
                    │  Python Automation    │
                    │  Admin SDK + Auth0 API │
                    │  Drift detection      │
                    │  Policy auditing      │
                    └──────────────────────┘
```

## Mock Company: NovaTech Solutions

100 employees across 10 departments with role-based access:

| Department | Headcount | Auth0 Role | AWS Permission Set | GWS 2SV Policy |
|-----------|-----------|-----------|-------------------|----------------|
| Engineering | 30 | `engineer` | PowerUser | Allow |
| Sales | 15 | `sales` | ReadOnly | Allow |
| Data | 10 | `data-engineer` | PowerUser | Allow |
| Marketing | 10 | `marketing` | ReadOnly | Allow |
| Product | 8 | `product` | ReadOnly | Allow |
| Executive | 7 | `executive` | ReadOnly | **Enforce** |
| IT-Ops | 5 | `it-admin` | Admin | **Enforce** |
| Finance | 5 | `finance` | ReadOnly | **Enforce** |
| Design | 5 | `designer` | ReadOnly | Allow |
| HR | 5 | `hr` | ReadOnly | **Enforce** |

User metadata: `{ department, role_title, cost_center, manager_email, start_date }`

## Key Scripts

| Script | What It Does |
|--------|-------------|
| `scripts/auth0/provision_users.py` | Bulk-provision users into Auth0 with department metadata and RBAC roles |
| `scripts/auth0/update_user_emails.py` | Migrate user email domains across Auth0 (batch Management API updates) |
| `scripts/auth0/actions/aws-saml-attribute-mapping.js` | Post-login Action: maps department → AWS Permission Set via SAML attributes |
| `scripts/auth0/actions/gws-saml-attribute-mapping.js` | Post-login Action: injects department metadata into GWS SAML assertions |
| `scripts/gws/create_ous.py` | Create department OUs in Google Cloud Identity via Directory API |
| `scripts/gws/provision_users.py` | Provision users into correct GWS OUs with org metadata |
| `scripts/gws/configure_2sv.py` | Audit per-OU 2-Step Verification policies via Cloud Identity Policy API |
| `scripts/lifecycle/sync_auth0_gws.py` | Cross-platform drift detection: Auth0 departments vs. GWS OU placement |

All scripts support `--dry-run` for safe change management and are idempotent (safe to re-run).

## Technical Decisions & Tradeoffs

**Why Auth0 instead of Okta?** Auth0 is part of the Okta ecosystem (acquired 2021) and shares the same identity concepts. The free developer tier requires no business domain. Auth0 Actions give code-level control over automation logic (Node.js) vs. Okta's visual Workflow builder — demonstrating protocol-level understanding rather than vendor-specific UI familiarity.

**Why Google Cloud Identity Free?** Full Admin Console, Directory API, and OU management without a paid Workspace license. The Cloud Identity Policy API is read-only on the Free edition (v1beta1 `create` returns 500, `patch` returns 400) — discovered through systematic API testing, documented, and worked around by using the Admin Console for writes and the API for audit/drift detection.

**Why Python against SaaS APIs?** Every automation in this project calls APIs directly — Auth0 Management API, Google Admin SDK Directory API, Cloud Identity Policy API, AWS CLI. No GUI clicks recorded as "automation." Scripts are the deployment artifact.

## Project Structure

```
scripts/
  auth0/                           # Auth0 Management API automation
    generate_users.py              #   Generate 100 mock NovaTech users
    provision_users.py             #   Bulk-provision users with roles + metadata
    update_user_emails.py          #   Domain migration via Management API
    actions/                       #   Auth0 post-login Actions (Node.js)
      aws-saml-attribute-mapping.js
      gws-saml-attribute-mapping.js
  gws/                             # Google Workspace Admin SDK automation
    create_ous.py                  #   OU creation via Directory API
    provision_users.py             #   User provisioning into OUs
    configure_2sv.py               #   2SV policy audit via Cloud Identity API
  lifecycle/                       # Cross-platform identity automation
    sync_auth0_gws.py             #   Auth0 → GWS drift detection + remediation
terraform/
  auth0/                           # Auth0 tenant-as-code (planned)
  aws/                             # AWS infrastructure (planned)
```

## Roadmap

| Phase | Focus | Status |
|-------|-------|--------|
| 1. Foundation & Platform Setup | Auth0 tenant, RBAC, SAML federation (AWS + GWS), MFA | Complete |
| 2. Google Workspace Architecture | Per-OU policies, data governance, third-party app governance, config-as-code | In Progress |
| 3. Slack Platform Engineering | SCIM provisioning, channel governance, app management via Admin API | Planned |
| 4. Cross-Platform Identity | Unified SCIM pipeline, access reviews, drift detection across all platforms | Planned |
| 5. Config-as-Code & AI Ops | Tenant config CI/CD, Claude MCP integrations, escalation runbooks | Planned |

## Identity Protocol Reference

| Concept | Auth0 (This Project) | Okta Equivalent |
|---------|---------------------|-----------------|
| User Store | `user_metadata` + `app_metadata` | Universal Directory |
| Automation | Actions (Node.js serverless) | Workflows (visual builder) |
| Provisioning | Management API + webhooks | SCIM to connected apps |
| SSO Federation | SAML/OIDC connections | SAML/OIDC app integrations |
| MFA | Guardian, adaptive MFA | Okta Verify, FastPass |
| Groups/Roles | Roles + Permissions + Organizations | Groups + Group Rules |
| Logs/Audit | Logs + Log Streams | System Log + Event Hooks |
| IaC | Terraform Provider | Terraform Provider |

## License

MIT
