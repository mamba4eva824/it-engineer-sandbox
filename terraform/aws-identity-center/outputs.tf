output "identity_center_instance_arn" {
  description = "IAM Identity Center instance ARN (auto-detected or from var)."
  value       = local.instance_arn
}

output "identity_store_id" {
  description = "Identity Store ID (auto-detected or from var)."
  value       = local.identity_store_id
}

output "portal_url" {
  description = "AWS access portal URL for SSO sign-in."
  value       = local.portal_url
}

output "developer_permission_set_arn" {
  description = "Developer permission set ARN (PowerUserAccess)."
  value       = aws_ssoadmin_permission_set.developer.arn
}

output "jml_audit_readonly_permission_set_arn" {
  description = "JMLAuditReadOnly permission set ARN (GRC DynamoDB read)."
  value       = aws_ssoadmin_permission_set.jml_audit_readonly.arn
}

output "developers_group_id" {
  description = "Identity Store Developers group ID."
  value       = aws_identitystore_group.developers.group_id
}

output "grc_group_id" {
  description = "Identity Store GRC group ID."
  value       = aws_identitystore_group.grc.group_id
}

output "provisioned_user_ids" {
  description = "Identity Store user IDs keyed by email."
  value       = { for email, user in aws_identitystore_user.member : email => user.user_id }
}
