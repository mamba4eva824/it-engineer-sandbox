# Lambda function + log group for the ohmgym license scanner.
#
# Source: lambdas/license_scanner/. Run build.sh before apply:
#   bash lambdas/license_scanner/build.sh

locals {
  lambda_zip_path = "${path.module}/../../lambdas/license_scanner/build/handler.zip"
}

data "local_file" "lambda_zip" {
  filename = local.lambda_zip_path
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name_prefix}"
  retention_in_days = var.lambda_log_retention_days
}

resource "aws_lambda_function" "license_scanner" {
  function_name = var.name_prefix
  description   = "Scans GitHub/Linear/Jira membership after leaver.completed; tickets incomplete or active seats to JSM."
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
      SECRETS_REGION              = var.aws_region
      SLACK_BOT_TOKEN_SECRET_NAME = var.slack_bot_token_secret_name
      GITHUB_READ_SECRET_NAME     = aws_secretsmanager_secret.read["github-read"].name
      LINEAR_READ_SECRET_NAME     = aws_secretsmanager_secret.read["linear-read"].name
      JIRA_READ_SECRET_NAME       = aws_secretsmanager_secret.read["jira-read"].name
      GITHUB_ORG                  = var.github_org
      JIRA_CLOUD_ID               = var.jira_cloud_id
      JIRA_EMAIL                  = var.jira_email
      JIRA_PROJECT_KEY            = var.jira_project_key
      JIRA_REQUEST_TYPE_ID        = var.jira_request_type_id
      JIRA_ISSUE_TYPE_ID          = var.jira_issue_type_id
      LINEAR_ORG_UUID             = var.linear_org_uuid
      DYNAMODB_TABLE_NAME         = aws_dynamodb_table.license_reclaim_logs.name
      DYNAMODB_TTL_DAYS           = tostring(var.dynamodb_ttl_days)
      SLACK_TEAM_ID               = var.slack_team_id
      LEAVER_CHANNEL_NAME         = var.leaver_channel_name
    }
  }

  depends_on = [aws_cloudwatch_log_group.lambda]
}
