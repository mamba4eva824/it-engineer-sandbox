# Optional IAM Identity Center resources (Path A/B).
# Activate by setting identity_center_instance_arn and identity_store_id in terraform.tfvars
# after enabling IAM Identity Center in the AWS account.

resource "aws_ssoadmin_permission_set" "jml_audit_readonly" {
  count = local.identity_center_enabled ? 1 : 0

  name             = "JMLAuditReadOnly"
  description      = "Read-only access to JML onboarding/offboarding DynamoDB audit tables."
  instance_arn     = var.identity_center_instance_arn
  session_duration = "PT8H"
}

resource "aws_ssoadmin_permission_set_inline_policy" "jml_audit_readonly" {
  count = local.identity_center_enabled ? 1 : 0

  inline_policy      = data.aws_iam_policy_document.grc_dynamodb_read.json
  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.jml_audit_readonly[0].arn
}

resource "aws_identitystore_user" "grc_analyst" {
  for_each = local.identity_center_enabled ? toset(var.sso_user_emails) : toset([])

  identity_store_id = var.identity_store_id
  display_name      = each.value
  user_name         = each.value

  name {
    given_name  = split("@", each.value)[0]
    family_name = "GRC"
  }

  emails {
    value   = each.value
    primary = true
  }
}

resource "aws_ssoadmin_account_assignment" "grc_jml_audit" {
  for_each = local.identity_center_enabled ? aws_identitystore_user.grc_analyst : {}

  instance_arn       = var.identity_center_instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.jml_audit_readonly[0].arn

  principal_id   = each.value.user_id
  principal_type = "USER"

  target_id   = var.sso_target_account_id != "" ? var.sso_target_account_id : local.account_id
  target_type = "AWS_ACCOUNT"
}
