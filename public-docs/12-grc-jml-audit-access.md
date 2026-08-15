# GRC JML Audit Access — Okta Identity, AWS Read Role, Claude Desktop Queries

GRC and Security analysts need read-only visibility into joiner/leaver automation and license reclaim outcomes without IT-Ops admin credentials. This work provisions **Bryan Wong** (GRC Analyst) in Okta, gates membership via the **`access-jml-audit`** group, and grants **scoped DynamoDB read access** to the JML onboarding/offboarding audit tables and `ohmgym-license-reclaim-logs`. Analysts query those tables from **Claude Desktop** using an AWS MCP connector and an assume-role profile.

Companion to:
- [10-aws-scheduled-onboarding-workflow.md](10-aws-scheduled-onboarding-workflow.md) — writes `ohmgym-onboarding-logs`
- [11-aws-scheduled-offboarding-workflow.md](11-aws-scheduled-offboarding-workflow.md) — writes `ohmgym-offboarding-logs`
- [16-license-reclamation-human-in-the-loop-roadmap.md](16-license-reclamation-human-in-the-loop-roadmap.md) — writes `ohmgym-license-reclaim-logs`
- [04-okta-migration.md](04-okta-migration.md) — Okta config-as-code pattern
- [02-aws-saml-federation.md](02-aws-saml-federation.md) — full Okta→AWS SAML upgrade path (deferred)

## Business context

| Item | Value |
|------|-------|
| Persona | Bryan Wong — GRC Analyst |
| Okta login / email | `weinreichchris@gmail.com` (personal Gmail; matches Claude Desktop Google OAuth) |
| Okta group | `access-jml-audit` — manual membership (like `access-gws`) |
| Onboarding audit table | `ohmgym-onboarding-logs` (`us-west-1`) |
| Offboarding audit table | `ohmgym-offboarding-logs` (`us-west-1`) |
| License reclaim audit table | `ohmgym-license-reclaim-logs` (`us-west-1`) |
| Retention | 90-day DynamoDB TTL on audit rows |

Audit tables store one row per `(run_date, user_id)` with status, department, role title, Okta response code, and batch metadata. License reclaim rows add `apps[]`, `jira_issue_key`, and reclaim status (`clean` / `ticketed` / `reclaimed` / `partial` / `error`). GRC uses them to review whether scheduled JML runs and seat reclamations succeeded without access to Okta API secrets, Lambda execution roles, or write paths.

## Access path implemented: Identity Center + C-hybrid

IAM Identity Center is **enabled** in OhmGym account `882248517627` (`ssoins-8201e2932463b8a0`, portal https://d-91670e0759.awsapps.com/start). **Path B** (Identity Center SSO) is managed in `terraform/aws-identity-center/`. **Path A** (Okta SAML federation) remains deferred.

**Also live:** Path C hybrid — standalone IAM role `ohmgym-grc-jml-audit-read` with read-only DynamoDB policy for Claude Desktop / CLI assume-role until Okta SAML (Phase 1).

| Path | Status |
|------|--------|
| A — Okta SAML → IAM Identity Center | Deferred (see [02-aws-saml-federation.md](02-aws-saml-federation.md)) |
| **B — Identity Center SSO** | **Live** in `882248517627` via `terraform/aws-identity-center/` |
| **C-hybrid — IAM assume role + Okta group** | **Live** (Claude Desktop / CLI) |

## End-to-end topology

```
Okta (integrator-2367542.okta.com)
  │
  ├── access-jml-audit group (manual membership)
  │     └── Bryan Wong (weinreichchris@gmail.com)
  │
  └── config-as-code: desired-state.json + reconcile_config.py
        (Terraform does NOT create Okta resources)

AWS (882248517627, us-west-1)
  │
  ├── IAM role: ohmgym-grc-jml-audit-read
  │     └── inline policy: dynamodb Query/Scan/GetItem/DescribeTable
  │           on ohmgym-onboarding-logs + ohmgym-offboarding-logs
  │           + ohmgym-license-reclaim-logs
  │
  └── DynamoDB audit tables (written by JML / license-scanner Lambdas)

Claude Desktop
  │
  ├── Personal OAuth: weinreichchris@gmail.com
  └── AWS API MCP (awslabs.aws-api-mcp-server)
        └── profile ohmgym-grc-jml-audit → assume role → DynamoDB read
```

## Platform ownership

| Platform | Tool | Creates |
|----------|------|---------|
| **AWS** | `terraform/aws-grc-audit/` | IAM role, DynamoDB read policy, optional SSO permission set (`sso.tf`) |
| **Okta** | `config/okta/desired-state.json` | `access-jml-audit` group declaration |
| **Okta** | `scripts/okta/reconcile_config.py --apply` | Applies group to live tenant |
| **Okta** | `scripts/okta/provision_users.py` | Bryan Wong from seed JSON |
| **Okta** | `scripts/grc/provision_grc_test_users.py` | External test user |
| **Okta** | `scripts/grc/assign_jml_audit_group.py` | User → group membership |
| **AWS state** | `config/aws/desired-state.json` | Identity Center verification + GRC access metadata |

## Configuration walkthrough

### 1. Okta — group and users

**Group** added to [`config/okta/desired-state.json`](../config/okta/desired-state.json):

- `access-jml-audit` — GRC/Security read-only JML audit access; manual membership.

**Users:**

- Bryan Wong in [`config/okta/grc_test_users.json`](../config/okta/grc_test_users.json) — login `weinreichchris@gmail.com`, name **Bryan Wong** (first/last name independent of email), role `GRC Analyst`.

**Apply (operator):**

```bash
python scripts/okta/reconcile_config.py --apply
python scripts/grc/provision_grc_test_users.py
python scripts/grc/assign_jml_audit_group.py
```

Requires project `.env` with Okta Private Key JWT credentials.

### 2. AWS — GRC read role (Terraform)

Stack: [`terraform/aws-grc-audit/`](../terraform/aws-grc-audit/)

```bash
cd terraform/aws-grc-audit
cp terraform.tfvars.example terraform.tfvars   # if needed
terraform init && terraform apply
```

**Resources created:**

| Resource | Name |
|----------|------|
| IAM role | `ohmgym-grc-jml-audit-read` |
| Inline role policy | `ohmgym-grc-jml-audit-dynamodb-read` |
| IAM policy (optional attach) | `ohmgym-grc-jml-audit-assume` |

**DynamoDB actions allowed:** `Query`, `Scan`, `GetItem`, `BatchGetItem`, `DescribeTable` on the three audit tables only. **Denied:** `PutItem`, `UpdateItem`, `DeleteItem`, and all other services.

**Path B upgrade:** Set `identity_center_instance_arn` and `identity_store_id` in `terraform.tfvars` to activate `JMLAuditReadOnly` permission set and Identity Store users in [`sso.tf`](../terraform/aws-grc-audit/sso.tf).

### 3. Claude Desktop — AWS MCP

See [claude-desktop-grc-aws-mcp.md](claude-desktop-grc-aws-mcp.md).

Append to `~/.aws/config`:

```ini
[profile ohmgym-grc-jml-audit]
region = us-west-1
role_arn = arn:aws:iam::882248517627:role/ohmgym-grc-jml-audit-read
source_profile = ohm-gym
```

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "aws-grc-audit": {
      "command": "uvx",
      "args": ["awslabs.aws-api-mcp-server@latest"],
      "env": {
        "AWS_REGION": "us-west-1",
        "AWS_API_MCP_PROFILE_NAME": "ohmgym-grc-jml-audit"
      }
    }
  }
}
```

**Example prompts** (use exact table names and `us-west-1` — see troubleshooting below):

- *Using aws-grc-audit MCP, scan `ohmgym-offboarding-logs` in `us-west-1`. Return first 10 items.*
- *Query `ohmgym-onboarding-logs` in `us-west-1` where `run_date` = "2026-06-15".*
- *Query `ohmgym-license-reclaim-logs` in `us-west-1` where `run_date` = "2026-08-15". Return login, status, apps, and jira_issue_key.*

**CLI alternative:** [`scripts/grc/query_jml_audit.py`](../scripts/grc/query_jml_audit.py)

### Troubleshooting AccessDenied from Claude MCP

If Claude reports AccessDenied and suggests adding policy for `off-boarding-logs` in **us-east-1**, the IAM role is usually **already correct**. Common causes:

| Mistake | Correct value |
|---------|---------------|
| Region `us-east-1` | **`us-west-1`** (JML stacks and audit tables) |
| Table `off-boarding-logs` | **`ohmgym-offboarding-logs`** |
| Table `onboarding-logs` | **`ohmgym-onboarding-logs`** |
| Table `license-reclaim-logs` | **`ohmgym-license-reclaim-logs`** |

Verify access with CLI (same profile as MCP):

```bash
AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py --table offboarding --scan --max-items 2
AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py --table reclaim --date 2026-08-15
```

If CLI succeeds, re-prompt Claude with exact table name and region. Full guide: [claude-desktop-grc-aws-mcp.md](claude-desktop-grc-aws-mcp.md).

```bash
AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py --table offboarding --scan --max-items 5
```

## Security controls

- **Least privilege:** Read-only on three named DynamoDB tables; no Secrets Manager, Lambda, or broad `dynamodb:*`.
- **Write denied:** `PutItem` returns `AccessDeniedException` under the GRC role (validated live).
- **Group-gated identity:** Only `access-jml-audit` members should receive AWS access; Okta group is the governance record.
- **Separation of identities:** Claude Desktop OAuth (`weinreichchris@gmail.com`) ≠ AWS role session (`ohmgym-grc-jml-audit-read/grc-test`).
- **TTL:** Audit rows auto-purge after 90 days; GRC sees only retained history.
- **No Okta in Terraform:** Prevents accidental cross-platform state coupling; Okta changes are auditable via reconcile reports.

## Validation evidence

| Check | Result |
|-------|--------|
| `terraform apply` in `terraform/aws-grc-audit/` | 3 resources created |
| `sts assume-role` → `ohmgym-grc-jml-audit-read` | Success |
| `dynamodb scan` on `ohmgym-offboarding-logs` as GRC role | Success (sample rows returned) |
| `dynamodb query` on `ohmgym-license-reclaim-logs` as GRC role | Success after IAM policy expand (P5-R1) |
| `dynamodb put-item` as GRC role | `AccessDeniedException` |
| IAM Identity Center instances | Active in `882248517627` (documented in `config/aws/desired-state.json`) |
| Okta group + users | Config committed; apply with `.env` credentials |

Integration tests: `tests/integration/test_jml_aws_live.py` includes `test_grc_audit_role_deployed` and policy scope checks.

## Repo layout

| Path | Role |
|------|------|
| [`config/okta/desired-state.json`](../config/okta/desired-state.json) | `access-jml-audit` group |
| [`config/okta/grc_test_users.json`](../config/okta/grc_test_users.json) | Bryan Wong (`weinreichchris@gmail.com`) |
| [`config/aws/desired-state.json`](../config/aws/desired-state.json) | AWS GRC access metadata |
| [`terraform/aws-grc-audit/`](../terraform/aws-grc-audit/) | IAM role + optional SSO |
| [`scripts/grc/`](../scripts/grc/) | Group assignment, test user provision, query CLI |
| [claude-desktop-grc-aws-mcp.md](claude-desktop-grc-aws-mcp.md) | Claude Desktop operator guide |

## Future work

1. **Enable IAM Identity Center** — activate Path B: set `identity_center_instance_arn` in Terraform; use `aws-sso` MCP with portal URL.
2. **Path A — Okta SAML** — Okta SAML app for AWS; assign `access-jml-audit` only; migrate external IdP per [02-aws-saml-federation.md](02-aws-saml-federation.md).
3. **API sync** — Okta group membership → Identity Center assignments (close governance vs enforcement gap).
4. **Reconcile user→group** — extend `reconcile_config.py` to manage `access-jml-audit` membership from config.
5. **Claude Enterprise** — Okta OIDC for gating Claude login itself (separate from AWS access).
