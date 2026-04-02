# IT Operations Sandbox

A hands-on lab environment that replicates real-world IT administration workflows for a mock 100-person SaaS startup ("NovaTech Solutions"). Built for interview preparation as a Senior IT / Enterprise SaaS Platform Engineer.

## What This Project Does

Uses **Auth0** (free tier, part of the Okta ecosystem) as the identity platform, **Google Cloud Identity Free** for collaboration, **Slack Developer Sandbox** for communications, **AWS Free Tier** for cloud infrastructure, and **Claude Code with MCP** for AI-powered IT operations to simulate:

- **Identity & Access Management** — SAML/OIDC federation, RBAC, SCIM-like provisioning
- **User Lifecycle Automation** — Joiner/Mover/Leaver workflows via Auth0 Actions and Management API
- **SaaS Platform Engineering** — Google Workspace tenant architecture, Slack workspace governance, third-party app management
- **AWS IAM Architecture** — Least-privilege roles, Terraform IaC, CI/CD pipelines
- **AI-Powered IT Ops** — Log analysis, ticket triage, drift detection via Claude MCP

## Architecture

```
                    ┌──────────────────────────┐
                    │      Auth0 Tenant        │
                    │      (SAML 2.0 IdP)      │
                    └────────────┬─────────────┘
                                 │
                    Post-Login Action injects
                    SAML attributes (department,
                    AccessLevel, RoleSessionName)
                                 │
       ┌─────────────┬──────────┼──────────┬──────────────┐
       │             │          │          │              │
  ┌────▼─────┐ ┌─────▼────┐ ┌──▼───┐ ┌───▼────┐ ┌───────▼───────┐
  │ AWS IAM  │ │  Google  │ │Slack │ │ SaaS   │ │ Auth0 Actions │
  │ Identity │ │  Cloud   │ │Enter-│ │ Apps   │ │ (JML, SAML    │
  │ Center   │ │ Identity │ │prise │ │ (Jira, │ │  Attribute    │
  │          │ │ (GWS)    │ │      │ │ GitHub)│ │  Mapping)     │
  │ Perm Sets│ └──────────┘ └──────┘ └────────┘ └───────┬───────┘
  │ Admin    │                                           │ Webhooks
  │ PowerUser│                                    ┌──────▼──────┐
  │ ReadOnly │                                    │ AWS Lambda  │
  └──────────┘                                    │ + DynamoDB  │
                                                  │ (Audit Log) │
                                                  └─────────────┘

     Claude Code ◄──── Auth0 MCP Server ────► Auth0 Management API
```

## Mock Company: NovaTech Solutions

100 employees across 10 departments with realistic role-based access:

| Department | Headcount | Auth0 Role | AWS Permission Set |
|-----------|-----------|-----------|-------------------|
| Engineering | 30 | `engineer` | PowerUser |
| Sales | 15 | `sales` | ReadOnly |
| Data | 10 | `data-engineer` | PowerUser |
| Marketing | 10 | `marketing` | ReadOnly |
| Product | 8 | `product` | ReadOnly |
| Executive | 7 | `executive` | ReadOnly |
| IT-Ops | 5 | `it-admin` | Admin |
| Finance | 5 | `finance` | ReadOnly |
| Design | 5 | `designer` | ReadOnly |
| HR | 5 | `hr` | ReadOnly |

## Getting Started

### Prerequisites

- Python 3.10+
- Node.js 18+ (for MCP servers)
- [Claude Code](https://claude.ai/code) with Claude Pro subscription
- Auth0 developer account (free at auth0.com)
- AWS Free Tier account
- Google Cloud Identity Free account (optional, for Phase 2+)
- Slack Developer Program sandbox (optional, for Phase 3+)

### 1. Clone and Install

```bash
cd "IT Operations Sandbox"
cp .env.example .env
pip install -r requirements.txt
```

### 2. Set Up Auth0

1. Create a free developer tenant at [auth0.com](https://auth0.com)
2. Create a **Machine-to-Machine Application** (Dashboard > Applications > Create)
3. Authorize it for the **Auth0 Management API** with all scopes (sandbox use)
4. Fill in your `.env`:
   ```
   AUTH0_DOMAIN=your-tenant.us.auth0.com
   AUTH0_CLIENT_ID=your_m2m_client_id
   AUTH0_CLIENT_SECRET=your_m2m_client_secret
   ```

### 3. Set Up AWS

1. Create a dedicated AWS account (separate from personal/production)
2. Create an IAM admin user with `AdministratorAccess` and generate an access key
3. Configure the CLI profile (credentials stored in `~/.aws/credentials`, never in `.env`):
   ```bash
   aws configure --profile novatech-sandbox
   ```
4. Add to `.env`:
   ```
   AWS_PROFILE=novatech-sandbox
   AWS_REGION=your_aws_region
   AWS_ACCOUNT_ID=your_account_id
   ```
5. Enable AWS Organizations and IAM Identity Center (console step)

### 4. Configure SAML Federation (Auth0 > AWS)

1. In **AWS IAM Identity Center** > Settings > Change identity source > **External identity provider**
2. Copy the **ACS URL** and **Issuer URL** from AWS
3. In **Auth0 Dashboard** > Applications > Create > Regular Web App > enable SAML2 addon:
   - Callback URL: paste ACS URL from AWS
   - Audience: paste Issuer URL from AWS
   - NameID Format: `urn:oasis:names:tc:SAML:1.1:nameid-format:emailAddress` (must be emailAddress, not persistent)
4. Download Auth0's IdP Metadata XML and upload to AWS IAM Identity Center
5. Add the SAML app's client ID to `.env`:
   ```
   AUTH0_SAML_CLIENT_ID=your_saml_app_client_id
   ```

### 5. Configure MCP

The project includes a pre-configured `.mcp.json` for Auth0 and filesystem MCP servers. Restart Claude Code to connect.

### 6. Generate and Provision Users

```bash
# Generate the 100-user dataset
python scripts/auth0/generate_users.py

# Preview without creating
python scripts/auth0/provision_users.py --dry-run

# Provision all 100 users into Auth0
python scripts/auth0/provision_users.py
```

## AWS Federation

Auth0 is federated to AWS IAM Identity Center via SAML 2.0. A post-login Auth0 Action maps user departments to SAML attributes, which AWS uses to assign Permission Sets.

### Permission Set Mapping

| Department | Permission Set | AWS Managed Policy |
|---|---|---|
| IT-Ops | Admin | `AdministratorAccess` |
| Engineering, Data | PowerUser | `PowerUserAccess` |
| Finance, Executive, Product, Design, HR, Sales, Marketing | ReadOnly | `ReadOnlyAccess` |

### How It Works

1. User navigates to the AWS SSO portal (SP-initiated login)
2. AWS redirects to Auth0 for authentication
3. Auth0 authenticates the user, then the **post-login Action** reads `user_metadata.department` and injects SAML attributes:
   - `RoleSessionName` — user's email
   - `AccessLevel` — mapped Permission Set (Admin/PowerUser/ReadOnly)
   - `SessionDuration` — 8 hours
4. Auth0 sends the SAML assertion to AWS's ACS endpoint
5. AWS matches the NameID (email) to the Identity Store user and grants the assigned Permission Set

### Key Files

- [aws-saml-attribute-mapping.js](scripts/auth0/actions/aws-saml-attribute-mapping.js) — Post-login Action source code

## Project Structure

```
.claude/
  agents/                          # Custom Claude Code agents
    identity-lifecycle-manager.md  #   Joiner/Mover/Leaver operations
    iam-policy-auditor.md          #   Auth0 + AWS security audits
    auth0-log-analyst.md           #   Security log analysis
    infrastructure-auditor.md      #   Terraform/AWS review
  commands/                        # Slash commands
    gsd.md                         #   /gsd — planning workflow
    ralf.md                        #   /ralf — execution workflow
    verify.md                      #   /verify — run all sandbox gates
    ship.md                        #   /ship — commit + PR creation
    help.md                        #   /help — command reference
  skills/                          # Claude Code skills
    onboard-user.md                #   /onboard-user <first> <last> <dept>
    offboard-user.md               #   /offboard-user <email>
    transfer-user.md               #   /transfer-user <email> <new_dept>
    access-review.md               #   /access-review [department]
    bulk-provision.md              #   /bulk-provision [count]
    session-report.md              #   /session-report [today|week|all]
  hooks/                           # Automated activity logging
scripts/
  auth0/
    generate_users.py              # Generate 100 mock NovaTech users
    provision_users.py             # Push users to Auth0 via Management API
    actions/
      aws-saml-attribute-mapping.js  # SAML attribute mapping Action (post-login)
  gws/                             # Google Workspace automation
    create_ous.py                  # Create OU structure in Cloud Identity
  aws/                             # AWS automation
  lifecycle/                       # JML automation
terraform/
  auth0/                           # Auth0 tenant-as-code
  aws/                             # AWS infrastructure
docs/                              # Architecture diagrams, reports (gitignored)
logs/                              # Auto-generated activity logs (gitignored)
```

## Claude Code Skills

| Skill | Usage | Description |
|-------|-------|-------------|
| `/onboard-user` | `/onboard-user Jane Doe Engineering` | Create user, assign roles, set metadata |
| `/offboard-user` | `/offboard-user jane.doe@company.com` | Revoke tokens, block account, remove roles |
| `/transfer-user` | `/transfer-user jane.doe@company.com Product` | Update department, reassign roles |
| `/access-review` | `/access-review Finance` | Audit users, flag anomalies, compliance report |
| `/bulk-provision` | `/bulk-provision 25` | Batch-create users from dataset |
| `/session-report` | `/session-report today` | Generate interview-ready activity report |

## Claude Code Agents

| Agent | Purpose |
|-------|---------|
| `identity-lifecycle-manager` | Full JML lifecycle — onboarding, transfers, offboarding, access reviews |
| `iam-policy-auditor` | Security audits across Auth0 RBAC and AWS IAM, compliance reporting |
| `auth0-log-analyst` | Analyze Auth0 tenant logs for anomalies, generate incident reports |
| `infrastructure-auditor` | Review Terraform configs, audit AWS resources, check free tier usage |

## Claude Code Commands

| Command | Description |
|---------|-------------|
| `/gsd` | Planning workflow — audit, acceptance criteria, plan, tasks, approval |
| `/ralf` | Execution loop — implement, verify, review, learn, complete |
| `/verify` | Run all sandbox verification gates (Auth0, AWS, GWS, Slack) |
| `/ship` | Final verification, commit, and PR creation |
| `/help` | Show all available commands with project context |

## 10-Week Roadmap

| Phase | Weeks | Focus | Status |
|-------|-------|-------|--------|
| 1. Foundation & Platform Setup | 1-2 | Auth0 tenant, RBAC, SAML federation, GWS + Slack setup, MFA | In Progress |
| 2. Google Workspace Architecture | 3-4 | OU design, Directory API automation, data governance, app governance | Not started |
| 3. Slack Platform Engineering | 5-6 | SCIM provisioning, channel governance, app management, Enterprise admin | Not started |
| 4. Identity Lifecycle Automation | 7-8 | Cross-platform JML workflows, Auth0 Actions + Lambda + webhooks | Not started |
| 5. AI-Powered IT Ops & Portfolio | 9-10 | Claude MCP integrations, log analysis, config-as-code, interview demos | Not started |

See [it_ops_lab.md](it_ops_lab.md) for the full detailed plan.

## Why Auth0?

Auth0 is part of the **Okta ecosystem** (acquired 2021) and shares the same identity concepts — SSO, SAML, OIDC, RBAC, lifecycle automation. The free developer tier requires only a personal email. All skills transfer directly to Okta interview conversations, and fluency in both platforms demonstrates deeper understanding.

## License

MIT
