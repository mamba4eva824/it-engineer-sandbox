data "aws_caller_identity" "current" {}

data "aws_ssoadmin_instances" "this" {}

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
  instance_arn      = var.identity_center_instance_arn != "" ? var.identity_center_instance_arn : one(data.aws_ssoadmin_instances.this.arns)
  identity_store_id = var.identity_store_id != "" ? var.identity_store_id : one(data.aws_ssoadmin_instances.this.identity_store_ids)

  account_id            = var.target_account_id != "" ? var.target_account_id : data.aws_caller_identity.current.account_id
  all_user_emails       = toset(concat(var.developer_user_emails, var.grc_user_emails))
  developer_user_emails = toset(var.developer_user_emails)
  grc_user_emails       = toset(var.grc_user_emails)
  portal_url            = "https://${local.identity_store_id}.awsapps.com/start"
}
