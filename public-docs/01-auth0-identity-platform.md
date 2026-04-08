# Auth0 Identity Platform Setup

## Overview

Configured Auth0 as the centralized Identity Provider for a mock 100-person SaaS company (NovaTech Solutions). Auth0 serves as the SAML 2.0 IdP federating into AWS and Google Workspace, with RBAC, lifecycle automation, and MCP-powered operations.

## Work Completed

### Tenant Configuration
- Created Auth0 developer tenant with Machine-to-Machine application for API automation
- Configured M2M client credentials grant for programmatic access to the Management API
- Connected Auth0 MCP server to Claude Code for AI-assisted identity operations

### User Provisioning (100 Users)
- Built `scripts/auth0/generate_users.py` to create a realistic 100-user dataset across 10 departments
- Built `scripts/auth0/provision_users.py` to bulk-provision users via the Management API with:
  - Department-based `user_metadata` (department, role_title, cost_center, manager_email, start_date)
  - Platform-specific `app_metadata` (aws_permission_set, github_team, jira_role)
  - Dry-run support for safe change management
  - Batch processing with rate limiting (10 users/batch, 1s pause)
  - Idempotent design — safe to re-run, skips existing users

### RBAC Role Architecture
- Created 10 Auth0 roles mapped to departments: `engineer`, `it-admin`, `finance`, `executive`, `data-engineer`, `product`, `designer`, `hr`, `sales`, `marketing`
- Roles assigned to all 100 users based on department metadata
- Resource server with 30 scoped permissions covering repos, databases, pipelines, billing, CRM, design assets, and more

### Email Domain Migration
- Built `scripts/auth0/update_user_emails.py` to migrate 100 users from one email domain to another via the Management API
- Updated both `email` and `user_metadata.manager_email` references in a single batch operation
- Demonstrates the identity reconciliation work involved in tenant consolidation (M&A scenario)

### Resource Server & Permission-to-Role Assignment

Created the "NovaTech Internal API" Resource Server with 30 scoped permissions and assigned them to roles following least-privilege principles. This completes the full RBAC chain: **Users → Roles → Permissions → Resource Server**.

**Permission-to-Role Matrix:**

| Role | Permissions | Count |
|---|---|---|
| `engineer` | `read:repos`, `write:repos`, `access:staging`, `access:ci-cd`, `read:databases`, `read:reports`, `read:analytics` | 7 |
| `data-engineer` | `read:repos`, `read:databases`, `write:databases`, `access:pipelines`, `access:ml-models`, `read:analytics`, `read:reports` | 7 |
| `it-admin` | `manage:users`, `manage:roles`, `manage:devices`, `read:logs`, `manage:infrastructure`, `read:reports`, `read:repos` | 7 |
| `finance` | `read:billing`, `approve:expenses`, `read:reports`, `read:compensation` | 4 |
| `executive` | `read:strategic-reports`, `approve:budgets`, `read:billing`, `read:analytics`, `read:reports` | 5 |
| `product` | `manage:products`, `read:user-research`, `read:analytics`, `read:reports` | 4 |
| `designer` | `manage:design-assets`, `read:design-assets`, `read:user-research`, `read:analytics` | 4 |
| `hr` | `manage:employees`, `read:compensation`, `read:reports` | 3 |
| `sales` | `read:crm`, `write:crm`, `read:reports`, `read:analytics` | 4 |
| `marketing` | `manage:campaigns`, `manage:content`, `read:analytics`, `read:crm`, `read:reports` | 5 |

**Design principles:**
- No role gets `access:production` by default — requires elevated access approval
- `it-admin` gets `manage:*` but NOT `access:production` or `write:databases` — admin access doesn't mean data write access
- `read:reports` is broadly granted; sensitive reports (`read:strategic-reports`, `read:compensation`) are restricted to Executive and HR/Finance respectively
- Engineering gets `write:repos` but Data doesn't — Data reads code, they don't push to it

**Verification:** Built `scripts/auth0/assign_role_permissions.py` with a `--verify` flag that queries the Management API and compares actual permissions against the desired matrix. All 10 roles verified as OK with 0 drift.

**Auth0 ↔ Okta mapping:** Resource Server = Okta Authorization Server. Permissions/scopes on the Resource Server = scopes on the Authorization Server. Role → Permission assignment = Group → Scope policy.

### Auth0 Actions (Post-Login)
- **AWS SAML Attribute Mapping**: Reads `user_metadata.department`, maps to Permission Set (Admin/PowerUser/ReadOnly), injects SAML attributes into the assertion — scoped to the AWS SAML app client_id only
- **GWS SAML Attribute Mapping**: Injects department and role_title into the Google Workspace SAML assertion — scoped to the GWS SAML app client_id only
- Both Actions run in the same post-login pipeline, each targeting its own Service Provider

## Key Scripts

| Script | Purpose |
|--------|---------|
| `scripts/auth0/generate_users.py` | Generate 100 mock NovaTech users with realistic metadata |
| `scripts/auth0/provision_users.py` | Bulk-provision users into Auth0 via Management API |
| `scripts/auth0/update_user_emails.py` | Batch email domain migration via Management API |
| `scripts/auth0/assign_role_permissions.py` | Assign 30 permissions to 10 roles (least-privilege matrix) with verify mode |
| `scripts/auth0/actions/aws-saml-attribute-mapping.js` | Post-login Action: department → AWS Permission Set |
| `scripts/auth0/actions/gws-saml-attribute-mapping.js` | Post-login Action: department + role into GWS assertion |

## Auth0 ↔ Okta Concept Mapping

| Concept | Auth0 (This Project) | Okta Equivalent |
|---------|---------------------|-----------------|
| User Store | `user_metadata` + `app_metadata` | Universal Directory |
| Automation | Actions (Node.js serverless) | Workflows (visual builder) |
| Provisioning | Management API + webhooks | SCIM to connected apps |
| SSO Federation | SAML/OIDC connections | SAML/OIDC app integrations |
| MFA | Guardian, adaptive MFA | Okta Verify, FastPass |
| Groups/Roles | Roles + Permissions + Organizations | Groups + Group Rules |
| Logs/Audit | Logs + Log Streams | System Log + Event Hooks |

## Technical Decisions

**Why Auth0?** Auth0 is part of the Okta ecosystem (acquired 2021). The free developer tier provides the full Management API, Actions, RBAC, and SAML/OIDC — same identity concepts as Okta but with code-level control over automation logic (Node.js Actions vs. Okta's visual Workflow builder). Fluency in both platforms demonstrates protocol-level understanding.

**Why Python SDK automation?** Every user operation — provisioning, role assignment, email migration — is done via Python scripts against the Management API, not console clicks. Scripts support `--dry-run`, are idempotent, and handle rate limiting. This is the "SCIM provisioning from the application side" pattern.
