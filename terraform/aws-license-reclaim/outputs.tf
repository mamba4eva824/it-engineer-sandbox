# Outputs useful for the operator after `terraform apply`.

output "function_name" {
  value       = aws_lambda_function.license_scanner.function_name
  description = "Lambda function name for aws lambda invoke / logs tail."
}

output "function_arn" {
  value = aws_lambda_function.license_scanner.arn
}

output "log_group_name" {
  value = aws_cloudwatch_log_group.lambda.name
}

output "dynamodb_table_name" {
  value = aws_dynamodb_table.license_reclaim_logs.name
}

output "dlq_url" {
  value = aws_sqs_queue.scanner_dlq.id
}

output "event_rule_arn" {
  value = aws_cloudwatch_event_rule.leaver_completed.arn
}

output "alarms_topic_arn" {
  value = aws_sns_topic.alarms.arn
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda_exec.arn
}

output "read_secret_names" {
  value       = [for s in aws_secretsmanager_secret.read : s.name]
  description = "Put values from .env: GITHUB_READ_TOKEN, LINEAR_API_KEY, JIRA_API_TOKEN."
}

output "write_secret_names" {
  value       = [for s in aws_secretsmanager_secret.write : s.name]
  description = "Phase 3 write shells. Scanner IAM cannot GetSecretValue these."
}
