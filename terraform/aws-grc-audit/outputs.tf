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

output "license_reclaim_table_arn" {
  description = "License reclaim audit table ARN."
  value       = data.aws_dynamodb_table.license_reclaim_logs.arn
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
