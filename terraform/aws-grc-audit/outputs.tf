output "grc_audit_role_arn" {
  description = "IAM role ARN for GRC read-only JML audit access (assume via AWS CLI or Claude Desktop)."
  value       = aws_iam_role.grc_jml_audit_read.arn
}

output "grc_audit_role_name" {
  description = "IAM role name."
  value       = aws_iam_role.grc_jml_audit_read.name
}

output "grc_assume_policy_arn" {
  description = "IAM policy ARN to attach to users who should assume the GRC audit role."
  value       = aws_iam_policy.grc_assume_role.arn
}

output "onboarding_table_arn" {
  description = "Onboarding audit table ARN."
  value       = data.aws_dynamodb_table.onboarding_logs.arn
}

output "offboarding_table_arn" {
  description = "Offboarding audit table ARN."
  value       = data.aws_dynamodb_table.offboarding_logs.arn
}

output "identity_center_enabled" {
  description = "Whether SSO permission set resources were created."
  value       = local.identity_center_enabled
}

output "sso_permission_set_arn" {
  description = "JMLAuditReadOnly permission set ARN (null when Identity Center disabled)."
  value       = local.identity_center_enabled ? aws_ssoadmin_permission_set.jml_audit_readonly[0].arn : null
}

output "aws_cli_profile_snippet" {
  description = "Append to ~/.aws/config for local / Claude Desktop assume-role access."
  value       = <<-EOT
    [profile ohmgym-grc-jml-audit]
    region = ${var.aws_region}
    role_arn = ${aws_iam_role.grc_jml_audit_read.arn}
    source_profile = default
  EOT
}
