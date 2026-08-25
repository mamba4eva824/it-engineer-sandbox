# IAM for the ohmgym-license-reclaim-orchestrator Lambda.
#
# Dedicated role, separate from scanner (iam.tf) and broker (broker_iam.tf).
# ADR-005: no GitHub/Linear/Jira write secrets — the broker is the only revoke
# path. Orchestrator reads findings, writes a planner map, POSTs the broker.
#
# DynamoDB: Query on jira_issue_key-index; UpdateItem allowed only for the
# `planner` attribute (token usage + plan snapshot). Broker still owns
# reclaim[] / row status.

resource "aws_iam_role" "orchestrator_exec" {
  name               = "${var.orchestrator_name_prefix}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  description        = "Execution role for the ohmgym license reclaim orchestrator Lambda."
}

data "aws_iam_policy_document" "orchestrator_logs" {
  statement {
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.orchestrator.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "orchestrator_logs" {
  name   = "${var.orchestrator_name_prefix}-logs"
  role   = aws_iam_role.orchestrator_exec.id
  policy = data.aws_iam_policy_document.orchestrator_logs.json
}

data "aws_iam_policy_document" "orchestrator_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.broker_webhook.arn,
      "${aws_secretsmanager_secret.broker_webhook.arn}-*",
      aws_secretsmanager_secret.read["jira-read"].arn,
      "${aws_secretsmanager_secret.read["jira-read"].arn}-*",
      var.slack_bot_token_secret_arn,
      "${var.slack_bot_token_secret_arn}-*",
      data.aws_secretsmanager_secret.openai.arn,
      "${data.aws_secretsmanager_secret.openai.arn}-*",
    ]
  }
}

resource "aws_iam_role_policy" "orchestrator_secrets" {
  name   = "${var.orchestrator_name_prefix}-secrets"
  role   = aws_iam_role.orchestrator_exec.id
  policy = data.aws_iam_policy_document.orchestrator_secrets.json
}

data "aws_iam_policy_document" "orchestrator_dynamodb" {
  statement {
    effect  = "Allow"
    actions = ["dynamodb:Query"]
    resources = [
      "${aws_dynamodb_table.license_reclaim_logs.arn}/index/jira_issue_key-index",
    ]
  }
  statement {
    sid     = "PlannerMapOnly"
    effect  = "Allow"
    actions = ["dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.license_reclaim_logs.arn,
    ]
    # dynamodb:Attributes conditions deny this UpdateItem because boto3/DDB
    # includes key attributes and nested planner map keys. Handler only SET planner.
  }
}

resource "aws_iam_role_policy" "orchestrator_dynamodb" {
  name   = "${var.orchestrator_name_prefix}-dynamodb"
  role   = aws_iam_role.orchestrator_exec.id
  policy = data.aws_iam_policy_document.orchestrator_dynamodb.json
}
