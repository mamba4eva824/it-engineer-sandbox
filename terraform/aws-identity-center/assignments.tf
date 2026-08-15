resource "aws_ssoadmin_account_assignment" "developers" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.developer.arn

  principal_id   = aws_identitystore_group.developers.group_id
  principal_type = "GROUP"

  target_id   = local.account_id
  target_type = "AWS_ACCOUNT"
}

resource "aws_ssoadmin_account_assignment" "grc" {
  instance_arn       = local.instance_arn
  permission_set_arn = aws_ssoadmin_permission_set.jml_audit_readonly.arn

  principal_id   = aws_identitystore_group.grc.group_id
  principal_type = "GROUP"

  target_id   = local.account_id
  target_type = "AWS_ACCOUNT"
}
