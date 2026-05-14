# Lambda function + log group for the ohmgym onboarding workflow.
#
# Source code lives at lambdas/onboarding_workflow/. Run build.sh once
# manually (or before each apply if handler.py changed) to produce the zip:
#   bash lambdas/onboarding_workflow/build.sh
# The local_file data source hashes that zip; source_code_hash on the
# function detects code changes and triggers a re-deploy on the next apply.
#
# No Function URL — this Lambda is invoked only by EventBridge Scheduler
# and the replay CLI via the lambda:Invoke API. No public HTTP surface.

locals {
  lambda_zip_path = "${path.module}/../../lambdas/onboarding_workflow/build/handler.zip"
}

data "local_file" "lambda_zip" {
  filename = local.lambda_zip_path
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name_prefix}"
  retention_in_days = var.lambda_log_retention_days
}

resource "aws_lambda_function" "onboarding_workflow" {
  function_name = var.name_prefix
  description   = "Proactively activates Okta STAGED users whose profile.startDate matches today (PT) and posts a batch summary to #joiner-it-ops."
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = var.lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = local.lambda_zip_path
  source_code_hash = data.local_file.lambda_zip.content_base64sha256

  environment {
    variables = {
      SECRETS_REGION                   = var.aws_region
      SLACK_BOT_TOKEN_SECRET_NAME      = var.slack_bot_token_secret_name
      OKTA_API_CLIENT_ID_SECRET_NAME   = var.okta_api_client_id_secret_name
      OKTA_API_KEY_ID_SECRET_NAME      = var.okta_api_key_id_secret_name
      OKTA_API_PRIVATE_KEY_SECRET_NAME = var.okta_api_private_key_secret_name
      OKTA_ORG_URL                     = var.okta_org_url
      DYNAMODB_TABLE_NAME              = aws_dynamodb_table.onboarding_logs.name
      DYNAMODB_TTL_DAYS                = tostring(var.dynamodb_ttl_days)
      SLACK_TEAM_ID                    = var.slack_team_id
      JOINER_CHANNEL_NAME              = var.joiner_channel_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}

# Allow EventBridge Scheduler to invoke this Lambda.
resource "aws_lambda_permission" "allow_scheduler" {
  statement_id  = "AllowSchedulerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.onboarding_workflow.function_name
  principal     = "scheduler.amazonaws.com"
  source_arn    = aws_scheduler_schedule.daily.arn
}
