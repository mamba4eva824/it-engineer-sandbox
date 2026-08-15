# IAM for the ohmgym-license-reclaim-broker Lambda.
#
# Dedicated role, separate from the scanner's (iam.tf) — ADR-005/ADR-006:
# the broker is the only thing with GetSecretValue on write ARNs, and the
# scanner role is never touched by this file. Broker also gets Query on the
# jira_issue_key GSI + UpdateItem on the table (scanner stays GetItem/PutItem
# only).

resource "aws_iam_role" "broker_exec" {
  name               = "${var.broker_name_prefix}-lambda-exec"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
  description        = "Execution role for the ohmgym license reclaim broker Lambda."
}

data "aws_iam_policy_document" "broker_logs" {
  statement {
    effect  = "Allow"
    actions = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "${aws_cloudwatch_log_group.broker.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "broker_logs" {
  name   = "${var.broker_name_prefix}-logs"
  role   = aws_iam_role.broker_exec.id
  policy = data.aws_iam_policy_document.broker_logs.json
}

data "aws_iam_policy_document" "broker_secrets" {
  statement {
    effect  = "Allow"
    actions = ["secretsmanager:GetSecretValue"]
    resources = concat(
      [
        aws_secretsmanager_secret.broker_webhook.arn,
        "${aws_secretsmanager_secret.broker_webhook.arn}-*",
        aws_secretsmanager_secret.read["jira-read"].arn,
        "${aws_secretsmanager_secret.read["jira-read"].arn}-*",
      ],
      [for k in ["github-write", "linear-write", "jira-write"] : aws_secretsmanager_secret.write[k].arn],
      [for k in ["github-write", "linear-write", "jira-write"] : "${aws_secretsmanager_secret.write[k].arn}-*"],
    )
  }
}

resource "aws_iam_role_policy" "broker_secrets" {
  name   = "${var.broker_name_prefix}-secrets"
  role   = aws_iam_role.broker_exec.id
  policy = data.aws_iam_policy_document.broker_secrets.json
}

data "aws_iam_policy_document" "broker_dynamodb" {
  statement {
    effect  = "Allow"
    actions = ["dynamodb:Query"]
    resources = [
      "${aws_dynamodb_table.license_reclaim_logs.arn}/index/jira_issue_key-index",
    ]
  }
  statement {
    effect  = "Allow"
    actions = ["dynamodb:UpdateItem"]
    resources = [
      aws_dynamodb_table.license_reclaim_logs.arn,
    ]
  }
}

resource "aws_iam_role_policy" "broker_dynamodb" {
  name   = "${var.broker_name_prefix}-dynamodb"
  role   = aws_iam_role.broker_exec.id
  policy = data.aws_iam_policy_document.broker_dynamodb.json
}
