# Data sources for existing JML audit tables (created by aws-onboarding / aws-offboarding stacks).

data "aws_caller_identity" "current" {}

data "aws_dynamodb_table" "onboarding_logs" {
  name = var.onboarding_table_name
}

data "aws_dynamodb_table" "offboarding_logs" {
  name = var.offboarding_table_name
}

locals {
  account_id              = data.aws_caller_identity.current.account_id
  identity_center_enabled = var.identity_center_instance_arn != ""
  trusted_principals      = length(var.trusted_principal_arns) > 0 ? var.trusted_principal_arns : [data.aws_caller_identity.current.arn]
}
