# Lambda function + Function URL for the license reclaim broker (Phase 3).
#
# Source: lambdas/license_reclaim_broker/. Run build.sh before apply:
#   bash lambdas/license_reclaim_broker/build.sh
#
# Function URL mirrors terraform/aws/lambda.tf (okta_activation_handler):
# authorization_type = "NONE", caller authenticates via a shared secret in
# the Authorization header (application-level check in handler.py), plus
# both the InvokeFunctionUrl and InvokeFunction permissions that newer AWS
# accounts' public-access controls require.

locals {
  broker_lambda_zip_path = "${path.module}/../../lambdas/license_reclaim_broker/build/handler.zip"
}

data "local_file" "broker_lambda_zip" {
  filename = local.broker_lambda_zip_path
}

resource "aws_cloudwatch_log_group" "broker" {
  name              = "/aws/lambda/${var.broker_name_prefix}"
  retention_in_days = var.lambda_log_retention_days
}

resource "aws_lambda_function" "license_reclaim_broker" {
  function_name = var.broker_name_prefix
  description   = "Allowlisted GitHub/Linear/Jira seat revoke, gated on a JSM ticket's scan findings."
  role          = aws_iam_role.broker_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = var.broker_lambda_timeout_seconds
  memory_size   = var.lambda_memory_mb

  filename         = local.broker_lambda_zip_path
  source_code_hash = data.local_file.broker_lambda_zip.content_base64sha256

  environment {
    variables = {
      SECRETS_REGION           = var.aws_region
      WEBHOOK_SECRET_NAME      = aws_secretsmanager_secret.broker_webhook.name
      GITHUB_WRITE_SECRET_NAME = aws_secretsmanager_secret.write["github-write"].name
      LINEAR_WRITE_SECRET_NAME = aws_secretsmanager_secret.write["linear-write"].name
      JIRA_WRITE_SECRET_NAME   = aws_secretsmanager_secret.write["jira-write"].name
      JIRA_READ_SECRET_NAME    = aws_secretsmanager_secret.read["jira-read"].name
      GITHUB_ORG               = var.github_org
      JIRA_CLOUD_ID            = var.jira_cloud_id
      JIRA_EMAIL               = var.jira_email
      LINEAR_ORG_UUID          = var.linear_org_uuid
      DYNAMODB_TABLE_NAME      = aws_dynamodb_table.license_reclaim_logs.name
      DYNAMODB_ISSUE_KEY_INDEX = "jira_issue_key-index"
    }
  }

  depends_on = [aws_cloudwatch_log_group.broker]
}

resource "aws_lambda_function_url" "license_reclaim_broker" {
  function_name      = aws_lambda_function.license_reclaim_broker.function_name
  authorization_type = "NONE" # caller authenticates via shared secret in the Authorization header
}

# Public Function URL access requires BOTH permissions on accounts with Lambda
# public-access controls (default on newer AWS accounts). See terraform/aws/lambda.tf.
resource "aws_lambda_permission" "broker_function_url_public" {
  statement_id           = "FunctionURLAllowPublicAccess"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.license_reclaim_broker.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "broker_function_url_invoke" {
  statement_id  = "FunctionURLAllowPublicInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.license_reclaim_broker.function_name
  principal     = "*"
}
