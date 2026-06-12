# Standalone IAM role for GRC read-only JML audit access.
# Active when IAM Identity Center is not enabled (Path C hybrid).
# Principals in trusted_principal_arns may sts:AssumeRole into this role.

data "aws_iam_policy_document" "grc_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "AWS"
      identifiers = local.trusted_principals
    }
  }
}

resource "aws_iam_role" "grc_jml_audit_read" {
  name               = "${var.name_prefix}-read"
  assume_role_policy = data.aws_iam_policy_document.grc_assume_role.json
  description        = "Read-only access to JML onboarding/offboarding DynamoDB audit tables for GRC analysts."
}

data "aws_iam_policy_document" "grc_dynamodb_read" {
  statement {
    sid    = "ReadOnboardingAudit"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      data.aws_dynamodb_table.onboarding_logs.arn,
      "${data.aws_dynamodb_table.onboarding_logs.arn}/index/*",
    ]
  }

  statement {
    sid    = "ReadOffboardingAudit"
    effect = "Allow"
    actions = [
      "dynamodb:Query",
      "dynamodb:Scan",
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:DescribeTable",
    ]
    resources = [
      data.aws_dynamodb_table.offboarding_logs.arn,
      "${data.aws_dynamodb_table.offboarding_logs.arn}/index/*",
    ]
  }
}

resource "aws_iam_role_policy" "grc_dynamodb_read" {
  name   = "${var.name_prefix}-dynamodb-read"
  role   = aws_iam_role.grc_jml_audit_read.id
  policy = data.aws_iam_policy_document.grc_dynamodb_read.json
}

# Optional: standalone policy operators can attach to IAM users who should assume the GRC role.
data "aws_iam_policy_document" "grc_assume_role_policy" {
  statement {
    sid    = "AssumeGrcJmlAuditRead"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
    ]
    resources = [
      aws_iam_role.grc_jml_audit_read.arn,
    ]
  }
}

resource "aws_iam_policy" "grc_assume_role" {
  name        = "${var.name_prefix}-assume"
  description = "Allows assuming the ohmgym-grc-jml-audit-read role for DynamoDB audit queries."
  policy      = data.aws_iam_policy_document.grc_assume_role_policy.json
}
