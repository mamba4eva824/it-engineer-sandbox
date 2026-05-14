# IAM for the ohmgym-onboarding-workflow Lambda and EventBridge Scheduler.
#
# Two principals, two roles:
#   - Lambda execution role: scoped to logs, secrets, dynamodb only.
#   - Scheduler role: scoped to lambda:InvokeFunction on this Lambda only.
#
# No AWS-managed policy attachments. All policies are inline + resource-scoped.
# No wildcards in resource ARNs except the trailing -* on Secrets Manager
# (the auto-generated 6-char suffix; not a security concern).

# -----------------------------------------------------------------------------
# Lambda execution role
# -----------------------------------------------------------------------------

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
  description        = "Execution role for the ohmgym onboarding workflow Lambda."
}

# CloudWatch Logs — scoped to this Lambda's log group only.
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

# Secrets Manager — scoped to the 4 us-west-1 replica ARNs only.
# The trailing -* is the Secrets Manager auto-suffix, NOT a wildcard escape.
data "aws_iam_policy_document" "lambda_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      "${var.slack_bot_token_replica_arn}-*",
      "${var.okta_api_client_id_replica_arn}-*",
      "${var.okta_api_key_id_replica_arn}-*",
      "${var.okta_api_private_key_replica_arn}-*",
      # Also allow the un-suffixed form (replica ARNs from terraform output don't include the suffix).
      var.slack_bot_token_replica_arn,
      var.okta_api_client_id_replica_arn,
      var.okta_api_key_id_replica_arn,
      var.okta_api_private_key_replica_arn,
    ]
  }
}

resource "aws_iam_role_policy" "lambda_secrets" {
  name   = "${var.name_prefix}-secrets"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_secrets.json
}

# DynamoDB — scoped to the onboarding_logs table only.
data "aws_iam_policy_document" "lambda_dynamodb" {
  statement {
    effect  = "Allow"
    actions = ["dynamodb:GetItem", "dynamodb:PutItem"]
    resources = [
      aws_dynamodb_table.onboarding_logs.arn,
    ]
  }
}

resource "aws_iam_role_policy" "lambda_dynamodb" {
  name   = "${var.name_prefix}-dynamodb"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.lambda_dynamodb.json
}

# -----------------------------------------------------------------------------
# EventBridge Scheduler role
# -----------------------------------------------------------------------------

data "aws_iam_policy_document" "scheduler_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${var.name_prefix}-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume_role.json
  description        = "Role assumed by EventBridge Scheduler to invoke the onboarding Lambda."
}

data "aws_iam_policy_document" "scheduler_invoke" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.onboarding_workflow.arn,
    ]
  }
}

resource "aws_iam_role_policy" "scheduler_invoke" {
  name   = "${var.name_prefix}-scheduler-invoke"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_invoke.json
}
