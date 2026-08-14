# Secrets Manager shells for license read/write tokens.
#
# Values are NOT stored in Terraform state. After apply:
#   aws secretsmanager put-secret-value --secret-id ohmgym-licenses/github-read \
#     --secret-string "$GITHUB_READ_TOKEN" --region us-west-1
#
# Scanner IAM grants GetSecretValue on READ ARNs only (ADR-006). Write shells
# exist so Phase 3 can attach a separate broker role without mixing stacks.

locals {
  read_secret_keys = [
    "github-read",
    "linear-read",
    "jira-read",
  ]
  write_secret_keys = [
    "github-write",
    "linear-write",
    "jira-write",
    "figma-read",
    "figma-write",
  ]
}

resource "aws_secretsmanager_secret" "read" {
  for_each    = toset(local.read_secret_keys)
  name        = "ohmgym-licenses/${each.key}"
  description = "License scanner READ credential (${each.key}). Put value from .env; never commit."
}

resource "aws_secretsmanager_secret" "write" {
  for_each    = toset(local.write_secret_keys)
  name        = "ohmgym-licenses/${each.key}"
  description = "License reclaim WRITE credential (${each.key}). Scanner IAM cannot read this. Phase 3."
}
