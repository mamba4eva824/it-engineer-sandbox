# IAM Identity Center permission sets for NovaTech sandbox personas.

resource "aws_ssoadmin_permission_set" "developer" {
  name             = "Developer"
  description      = "PowerUser access for Engineering and other developer personas in the sandbox account."
  instance_arn     = var.identity_center_instance_arn
  session_duration = "PT8H"
}

resource "aws_ssoadmin_managed_policy_attachment" "developer_poweruser" {
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.developer.arn
  managed_policy_arn = "arn:aws:iam::aws:policy/PowerUserAccess"
}

resource "aws_ssoadmin_permission_set" "jml_audit_readonly" {
  name             = "JMLAuditReadOnly"
  description      = "Read-only access to JML onboarding/offboarding DynamoDB audit tables (GRC)."
  instance_arn     = var.identity_center_instance_arn
  session_duration = "PT8H"
}

data "aws_iam_policy_document" "jml_audit_dynamodb_read" {
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

resource "aws_ssoadmin_permission_set_inline_policy" "jml_audit_readonly" {
  inline_policy      = data.aws_iam_policy_document.jml_audit_dynamodb_read.json
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.jml_audit_readonly.arn
}
