data "aws_secretsmanager_secret" "openai" {
  name = var.openai_secret_name
}

# Lambda function + log group for the license reclaim orchestrator (Phase 5).
#
# Source: lambdas/license_reclaim_orchestrator/. Run build.sh before apply:
#   bash lambdas/license_reclaim_orchestrator/build.sh
#
# Always deployed so CLI (`orchestrate.py` / aws lambda invoke) works while
# var.enable_orchestrator is false. EventBridge target enablement is on the
# parent rule in eventbridge.tf.

locals {
  orchestrator_lambda_zip_path = "${path.module}/../../lambdas/license_reclaim_orchestrator/build/handler.zip"
}

data "local_file" "orchestrator_lambda_zip" {
  filename = local.orchestrator_lambda_zip_path
}

resource "aws_cloudwatch_log_group" "orchestrator" {
  name              = "/aws/lambda/${var.orchestrator_name_prefix}"
  retention_in_days = var.lambda_log_retention_days
}

resource "aws_lambda_function" "license_reclaim_orchestrator" {
  function_name = var.orchestrator_name_prefix
  description   = "OpenAI GPT-5.6 Luna ReclaimPlan after license.scan.complete; POSTs the same reclaim broker. EventBridge target off unless enable_orchestrator."
  role          = aws_iam_role.orchestrator_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = var.orchestrator_lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = local.orchestrator_lambda_zip_path
  source_code_hash = data.local_file.orchestrator_lambda_zip.content_base64sha256

  environment {
    variables = {
      SECRETS_REGION              = var.aws_region
      OPENAI_SECRET_NAME          = var.openai_secret_name
      OPENAI_MODEL_ID             = var.openai_model_id
      OPENAI_BASE_URL             = var.openai_base_url
      OPENAI_MAX_TOKENS           = tostring(var.openai_max_tokens)
      ORCHESTRATOR_AUTO_RUN       = var.enable_orchestrator ? "true" : "false"
      WEBHOOK_SECRET_NAME         = aws_secretsmanager_secret.broker_webhook.name
      BROKER_FUNCTION_URL         = aws_lambda_function_url.license_reclaim_broker.function_url
      JIRA_READ_SECRET_NAME       = aws_secretsmanager_secret.read["jira-read"].name
      JIRA_CLOUD_ID               = var.jira_cloud_id
      JIRA_EMAIL                  = var.jira_email
      DYNAMODB_TABLE_NAME         = aws_dynamodb_table.license_reclaim_logs.name
      DYNAMODB_ISSUE_KEY_INDEX    = "jira_issue_key-index"
      SLACK_BOT_TOKEN_SECRET_NAME = var.slack_bot_token_secret_name
      SLACK_TEAM_ID               = var.slack_team_id
      LEAVER_CHANNEL_NAME         = var.leaver_channel_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.orchestrator]
}
