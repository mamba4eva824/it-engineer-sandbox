# ARNs for consumer stacks (terraform/aws, aws-onboarding, aws-offboarding).

output "slack_bot_token_secret_arn" {
  description = "ARN for ohmgym-jml/slack-bot-token."
  value       = aws_secretsmanager_secret.slack_bot_token.arn
}

output "okta_api_client_id_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-client-id."
  value       = aws_secretsmanager_secret.okta_api_client_id.arn
}

output "okta_api_key_id_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-key-id."
  value       = aws_secretsmanager_secret.okta_api_key_id.arn
}

output "okta_api_private_key_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-private-key."
  value       = aws_secretsmanager_secret.okta_api_private_key.arn
}

output "okta_webhook_secret_arn" {
  description = "ARN for ohmgym-jml/okta-webhook-secret (activation workflow only)."
  value       = aws_secretsmanager_secret.okta_webhook_secret.arn
}
