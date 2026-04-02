# IT Operations Sandbox

## Project Purpose
Interview preparation lab targeting **Enterprise SaaS Platform Engineering** roles. Replicates real-world collaboration platform administration and identity automation using Auth0 (IdP), Google Cloud Identity Free (collaboration), Slack Developer Sandbox (communication), and AWS Free Tier (infrastructure) — with Claude MCP for AI-powered operations.

**Target Role:** Enterprise SaaS Engineer — owning tenant-wide architecture for Google Workspace, Slack, and the surrounding identity/collaboration ecosystem. Emphasis on going beyond admin consoles to solve problems in code (Python against SaaS APIs), SCIM provisioning from the application side, data governance, and platform configuration as code.

## Mock Company: "NovaTech Solutions"
A 100-person SaaS startup with departments: Engineering, IT-Ops, Finance, Executive, Data, Product, Design, HR, Sales, Marketing.

## Architecture
- **Identity Provider**: Auth0 Developer Tenant (`your-tenant.us.auth0.com`) — SAML/OIDC, RBAC, Actions, Log Streams
- **Collaboration**: Google Cloud Identity Free (`your-domain.com`) — OUs, Directory API, Admin SDK, data governance
- **Communication**: Slack Developer Sandbox — Admin API, SCIM, channel governance, app management
- **Cloud**: AWS Free Tier (IAM Identity Center, Lambda, DynamoDB) — deemphasized; "cloud infrastructure lives with separate teams"
- **Config-as-Code**: Python scripts for GWS/Slack, Terraform for Auth0/AWS, GitHub Actions CI/CD
- **MCP Servers**: Auth0, Filesystem (future: GWS, Slack)

## Directory Structure
```
.claude/
  agents/          # Custom Claude Code agents for IT ops tasks
  skills/          # Custom Claude Code skills (slash commands)
  hooks/           # Activity logging hooks
scripts/
  auth0/           # Auth0 Management API scripts (Python)
  gws/             # Google Workspace Admin SDK scripts (Python)
  slack/            # Slack Admin API scripts (Python)
  lifecycle/       # Cross-platform Joiner/Mover/Leaver automation
config/
  auth0/           # Auth0 tenant config-as-code
  gws/             # Google Workspace config-as-code
  slack/            # Slack workspace config-as-code
  aws/             # AWS config-as-code
terraform/
  auth0/           # Auth0 Terraform provider
  aws/             # AWS infrastructure
docs/              # Architecture diagrams, runbooks, resume, reports
logs/              # Auto-generated activity logs (gitignored)
```

## Platform Credentials & MCP

### Auth0 MCP Server
Configured in `.mcp.json`. Credentials stored in system keychain via `auth0-mcp-server init`.

### Auth0 Free Tier Limits
- 25,000 MAU — more than enough for 100 sandbox users
- 1,000 M2M tokens/month — budget API calls during bulk operations
- Actions, Log Streams, RBAC, Organizations all included

### Google Cloud Identity Free
- Domain: `your-domain.com`
- Admin Console, Admin SDK, Directory API, OU management, Groups
- No Gmail/Drive (Cloud Identity Free), but full directory and policy management

### Slack Developer Sandbox
- Enterprise-grade workspace with Admin API access
- SCIM API, App Management API, Audit Logs API
- 8 users max per sandbox, 6-month lifespan (renewable)

## Key Conventions
- All automation is **Python against SaaS APIs** — not console clicks
- User metadata follows: `{ department, role_title, cost_center, manager_email, start_date }`
- App metadata follows: `{ aws_permission_set, github_team, gws_ou, slack_user_group }`
- Roles map to platform access: Engineering→PowerUser+repos, IT-Ops→Admin+manage:users, Finance→ReadOnly+billing

## Resume Reference
Christopher's resume is at `docs/Senior IT Engineer Resume .md`. When generating reports, audit findings, or interview talking points, map sandbox work to the target JD requirements and these specific experiences:

### JD Requirements → Sandbox → Resume Mapping
| JD Requirement | Sandbox Deliverable | Resume Experience |
|---|---|---|
| Google Workspace tenant architecture | GWS OU architecture, per-OU policies, Admin SDK automation | Google Workspace admin with HIPAA exception groups (Headspace) |
| Slack administration and APIs | Slack Admin API, SCIM provisioning, channel governance, app governance | LLM-powered Slack chatbot with LangChain RAG (Headspace) |
| SSO connections and SCIM from application side | Auth0 → GWS SAML, Auth0 → Slack OIDC, SCIM provisioning pipeline | Okta SCIM/SAML/SSO integrations, zero-touch JML workflows (Headspace) |
| Data governance / compartmentalization | Per-OU sharing policies, DLP rules, Drive permission auditing | HIPAA-compliant PHI access controls, least-privilege (Headspace) |
| Python against SaaS APIs | All automation in Python against Admin SDK, Slack API, Auth0 API | LangChain RAG chatbot, FastAPI, Python automation (Headspace + Buffett AI) |
| Platform config-as-code | Full config repo with CI/CD for GWS + Slack + Auth0 | CI/CD pipelines, Terraform, branch-based promotion (Buffett AI) |
| Third-party app governance | GWS + Slack app risk audits, OAuth scope analysis | HIPAA-compliant third-party app integrations (Headspace) |
| Partner with Security on SaaS hardening | Cross-platform security posture reports, access reviews | Quarterly access reviews, SOC 2 Type II readiness (Headspace) |
| Final escalation tier | Vendor escalation runbooks with diagnostic scripts | IT Operations lead, cross-functional partner (Headspace) |
| Catch drift | Cross-platform drift detection comparing desired vs. actual state | Least-privilege IAM across 48 resources (Buffett AI) |

### Interview Framing Rule
Every output from agents and skills should be expressible as: "I hit the ceiling of what the admin console could do and solved it in code. In my sandbox, I built [X], which mirrors [JD requirement] and my experience at [Headspace/Buffett AI] where I [specific achievement]."

## Phase Tracking
See `it_ops_lab.md` for the full 10-week roadmap. Current focus: Phase 1 (Foundation & Platform Setup — Auth0 done, GWS + Slack pending).
