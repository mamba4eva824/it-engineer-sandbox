# Outputs the operator needs after `terraform apply`.
#
# function_url is what you paste into the Okta Event Hook configuration UI.
# log_group_name is what you tail to see the webhook fire:
#   aws logs tail /aws/lambda/novatech-okta-hook --follow

output "function_url" {
  description = "HTTPS endpoint the Okta event hook posts to. Paste into Okta Admin → Workflow → Event Hooks."
  value       = aws_lambda_function_url.okta_activation_handler.function_url
}

output "function_name" {
  description = "Lambda function name; useful for `aws logs tail` or `aws lambda invoke`."
  value       = aws_lambda_function.okta_activation_handler.function_name
}

output "log_group_name" {
  description = "CloudWatch log group; tail with `aws logs tail <name> --follow`."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "okta_webhook_secret_arn" {
  description = "ARN of the Secrets Manager entry holding the Okta-shared Authorization secret."
  value       = aws_secretsmanager_secret.okta_webhook_secret.arn
}

output "slack_bot_token_secret_arn" {
  description = "ARN of the Secrets Manager entry holding the Slack bot token."
  value       = aws_secretsmanager_secret.slack_bot_token.arn
}

output "lambda_role_arn" {
  description = "Execution role ARN; useful when running `iam-policy-auditor` reviews."
  value       = aws_iam_role.lambda_exec.arn
}
