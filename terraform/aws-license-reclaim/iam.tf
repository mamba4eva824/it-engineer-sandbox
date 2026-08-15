# IAM for the ohmgym-license-scanner Lambda.
#
# GetSecretValue on READ license secrets + shared Slack token only.
# Write secret ARNs are created in this stack but omitted from IAM (ADR-006).
# No Okta secrets — github_username arrives on leaver.completed.

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
  description        = "Execution role for the ohmgym license scanner Lambda."
}

data "aws_iam_policy_document" "lambda_logs" {
  statement {
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.lambda.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "lambda_logs" {
  name   = "${var.name_prefix}-logs"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_logs.json
}

data "aws_iam_policy_document" "lambda_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [
        var.slack_bot_token_secret_arn,
        "${var.slack_bot_token_secret_arn}-*",
      ],
      [for s in aws_secretsmanager_secret.read : s.arn],
      [for s in aws_secretsmanager_secret.read : "${s.arn}-*"],
    )
  }
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name   = "${var.name_prefix}-secrets"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_secrets.json
}

data "aws_iam_policy_document" "lambda_dynamodb" {
  statement {
    effect  = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [
      aws_dynamodb_table.license_reclaim_logs.arn,
    ]
  }
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name   = "${var.name_prefix}-dynamodb"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_dynamodb.json
}
