# Data sources for existing JML / license-reclaim audit tables
# (created by aws-onboarding / aws-offboarding / aws-license-reclaim stacks).

data "aws_caller_identity" "current" {}

data "aws_dynamodb_table" "onboarding_logs" {
  name = var.onboarding_table_name
}

data "aws_dynamodb_table" "offboarding_logs" {
  name = var.offboarding_table_name
}

data "aws_dynamodb_table" "license_reclaim_logs" {
  name = var.license_reclaim_table_name
}

locals {
  account_id         = data.aws_caller_identity.current.account_id
  trusted_principals = length(var.trusted_principal_arns) > 0 ? var.trusted_principal_arns : [data.aws_caller_identity.current.arn]
}
