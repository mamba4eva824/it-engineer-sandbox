# Claude Desktop — AWS MCP for GRC JML Audit Queries

Operator guide for querying `ohmgym-onboarding-logs`, `ohmgym-offboarding-logs`, and `ohmgym-license-reclaim-logs` via Claude Desktop using the `ohmgym-grc-jml-audit-read` IAM role.

Companion: [12-grc-jml-audit-access.md](12-grc-jml-audit-access.md)

## Prerequisites

- `terraform apply` completed in `terraform/aws-grc-audit/`
- Okta user in `access-jml-audit` (governance record; AWS access is via IAM assume role)
- AWS CLI `ohm-gym` profile (or `source_profile`) can call `sts:AssumeRole` on `ohmgym-grc-jml-audit-read`

## 1. AWS profile (`~/.aws/config`)

```ini
[profile ohmgym-grc-jml-audit]
region = us-west-1
role_arn = arn:aws:iam::882248517627:role/ohmgym-grc-jml-audit-read
source_profile = ohm-gym
```

**Important:** JML audit tables live in **us-west-1**, not `us-east-1`. Your `[default]` profile may be `us-east-1`; the GRC profile overrides region to `us-west-1` when MCP uses `AWS_API_MCP_PROFILE_NAME`.

## 2. Claude Desktop MCP (`claude_desktop_config.json`)

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

Restart Claude Desktop after editing.

## 3. Correct table names and region

| Wrong (common mistakes) | Correct |
|-------------------------|---------|
| `off-boarding-logs` | `ohmgym-offboarding-logs` |
| `onboarding-logs` | `ohmgym-onboarding-logs` |
| `license-reclaim-logs` | `ohmgym-license-reclaim-logs` |
| `us-east-1` | `us-west-1` |

## 4. Example prompts (copy-paste)

Use **exact** table names and region in the prompt so the model does not guess:

```
Using the aws-grc-audit MCP server, scan ohmgym-offboarding-logs in us-west-1.
Return the first 10 items. Profile: ohmgym-grc-jml-audit.
```

```
Query ohmgym-onboarding-logs in us-west-1 where run_date = "2026-06-15".
Use partition key run_date. Max 20 items.
```

```
Query ohmgym-license-reclaim-logs in us-west-1 where run_date = "2026-08-15".
Return login, status, apps, and jira_issue_key.
```

```
DescribeTable on ohmgym-offboarding-logs in us-west-1 to confirm the table exists.
```

## 5. CLI fallback (same IAM path)

```bash
AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py \
  --table offboarding --scan --max-items 5

AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py \
  --table onboarding --date 2026-06-15

AWS_PROFILE=ohmgym-grc-jml-audit python scripts/grc/query_jml_audit.py \
  --table reclaim --date 2026-08-15
```

## Troubleshooting

### AccessDenied on Scan/Query

**Symptom:** Claude reports `AccessDeniedException` and suggests adding IAM policy for `off-boarding-logs` in `us-east-1`.

**Cause:** The IAM role is correct. Claude (or the MCP call) used the **wrong region** and/or **wrong table name**. The GRC policy only allows:

- `arn:aws:dynamodb:us-west-1:882248517627:table/ohmgym-onboarding-logs`
- `arn:aws:dynamodb:us-west-1:882248517627:table/ohmgym-offboarding-logs`
- `arn:aws:dynamodb:us-west-1:882248517627:table/ohmgym-license-reclaim-logs`

Access denied in `us-east-1` is **expected** — it does not mean the policy is missing.

**Fix:**

1. Re-prompt with exact names: `ohmgym-offboarding-logs`, `us-west-1`
2. Confirm MCP env: `AWS_REGION=us-west-1`, `AWS_API_MCP_PROFILE_NAME=ohmgym-grc-jml-audit`
3. Restart Claude Desktop after config changes
4. Verify with CLI (above) — if CLI works, IAM is fine; fix the prompt

**Verify IAM policy (operator):**

```bash
aws iam get-role-policy \
  --role-name ohmgym-grc-jml-audit-read \
  --policy-name ohmgym-grc-jml-audit-dynamodb-read \
  --query 'PolicyDocument.Statement[*].Resource' \
  --output json
```

### AssumeRole fails

Ensure `ohm-gym` (or `source_profile`) has permission to assume `ohmgym-grc-jml-audit-read`, or add your IAM user ARN to `trusted_principal_arns` in `terraform/aws-grc-audit/terraform.tfvars` and re-apply.

### PutItem denied (expected)

GRC role is read-only. `PutItem` must return `AccessDeniedException` — that is correct behavior.

## What the GRC role can and cannot do

| Allowed | Denied |
|---------|--------|
| `Query`, `Scan`, `GetItem`, `BatchGetItem`, `DescribeTable` on three audit tables | `PutItem`, `UpdateItem`, `DeleteItem` |
| `us-west-1` only | Other regions, Secrets Manager, Lambda, S3 |
