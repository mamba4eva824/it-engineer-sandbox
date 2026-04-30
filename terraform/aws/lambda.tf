# Lambda function + Function URL.
#
# Source code lives at lambdas/okta_activation_handler/. Run build.sh once
# manually (or before each apply if handler.py changed) to produce the zip:
#   bash lambdas/okta_activation_handler/build.sh
# The archive_file data source then hashes that zip; source_code_hash on the
# function detects code changes and triggers a re-deploy on the next apply.
#
# CloudWatch log group is declared explicitly (rather than letting Lambda
# auto-create it on first invocation) so we can set retention and have it
# tracked in Terraform state. No alarms (intentional — sandbox observability
# is "tail the logs," not "page on threshold").

locals {
  lambda_zip_path = "${path.module}/../../lambdas/okta_activation_handler/build/handler.zip"
}

# Hash the externally-built zip so source_code_hash detects changes.
# Run `bash lambdas/okta_activation_handler/build.sh` before `terraform plan`
# any time handler.py or requirements.txt has changed.
data "local_file" "lambda_zip" {
  filename = local.lambda_zip_path
}

resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${var.name_prefix}"
  retention_in_days = var.lambda_log_retention_days
}

resource "aws_lambda_function" "okta_activation_handler" {
  function_name = var.name_prefix
  description   = "Receives Okta event hook POSTs (user.account.update_password) and posts to Slack #joiner-it-ops."
  role          = aws_iam_role.lambda_exec.arn
  handler       = "handler.lambda_handler"
  runtime       = "python3.12"
  architectures = ["x86_64"]
  timeout       = 10
  memory_size   = 256

  filename         = local.lambda_zip_path
  source_code_hash = data.local_file.lambda_zip.content_base64sha256

  environment {
    variables = {
      SECRETS_REGION              = var.aws_region
      OKTA_SECRET_NAME            = aws_secretsmanager_secret.okta_webhook_secret.name
      SLACK_BOT_TOKEN_SECRET_NAME = aws_secretsmanager_secret.slack_bot_token.name
      SLACK_TEAM_ID               = var.slack_team_id
      JOINER_CHANNEL_NAME         = var.joiner_channel_name
    }
  }

  # Make sure the log group exists before the Lambda's first invocation;
  # otherwise Lambda auto-creates one with the default retention and Terraform
  # would complain on next plan.
  depends_on = [aws_cloudwatch_log_group.lambda]
}

resource "aws_lambda_function_url" "okta_activation_handler" {
  function_name      = aws_lambda_function.okta_activation_handler.function_name
  authorization_type = "NONE" # Okta authenticates via shared secret in the body's Authorization header
}
