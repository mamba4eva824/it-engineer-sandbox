# Outputs useful for the operator after `terraform apply`.

output "function_name" {
  description = "Lambda function name; useful for `aws lambda invoke` from the replay CLI and `aws logs tail`."
  value       = aws_lambda_function.onboarding_workflow.function_name
}

output "function_arn" {
  description = "Lambda function ARN."
  value       = aws_lambda_function.onboarding_workflow.arn
}

output "log_group_name" {
  description = "CloudWatch log group; tail with `aws logs tail <name> --follow --region us-west-1`."
  value       = aws_cloudwatch_log_group.lambda.name
}

output "dynamodb_table_name" {
  description = "Audit-trail table name."
  value       = aws_dynamodb_table.onboarding_logs.name
}

output "scheduler_arn" {
  description = "EventBridge Scheduler ARN; pause it with `aws scheduler update-schedule` if you need to disable the daily run."
  value       = aws_scheduler_schedule.daily.arn
}

output "alarms_topic_arn" {
  description = "SNS topic ARN that the error alarm fans out to."
  value       = aws_sns_topic.alarms.arn
}

output "lambda_role_arn" {
  description = "Lambda execution role ARN; useful for iam-policy-auditor reviews."
  value       = aws_iam_role.lambda_exec.arn
}
