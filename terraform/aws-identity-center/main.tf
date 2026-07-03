data "aws_caller_identity" "current" {}

data "aws_dynamodb_table" "onboarding_logs" {
  name = var.onboarding_table_name
}

data "aws_dynamodb_table" "offboarding_logs" {
  name = var.offboarding_table_name
}

locals {
  account_id            = var.target_account_id != "" ? var.target_account_id : data.aws_caller_identity.current.account_id
  all_user_emails       = toset(concat(var.developer_user_emails, var.grc_user_emails))
  developer_user_emails = toset(var.developer_user_emails)
  grc_user_emails       = toset(var.grc_user_emails)
}
