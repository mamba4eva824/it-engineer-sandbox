# IAM execution role + scoped policies for ohmgym-activation-workflow.

data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda_exec" {
  name               = "${var.name_prefix}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  description        = "Execution role for the ohmgym-activation-workflow Lambda."
}

resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_exec.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

data "aws_iam_policy_document" "secrets_read" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      "${var.slack_bot_token_secret_arn}-*",
      var.slack_bot_token_secret_arn,
      "${var.okta_api_client_id_secret_arn}-*",
      var.okta_api_client_id_secret_arn,
      "${var.okta_api_key_id_secret_arn}-*",
      var.okta_api_key_id_secret_arn,
      "${var.okta_api_private_key_secret_arn}-*",
      var.okta_api_private_key_secret_arn,
      "${var.okta_webhook_secret_arn}-*",
      var.okta_webhook_secret_arn,
    ]
  }
}

resource "aws_iam_role_policy" "secrets_read" {
  name   = "${var.name_prefix}-secrets-read"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.secrets_read.json
}
