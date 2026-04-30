# IAM execution role + scoped policies for the Lambda.
#
# Two policies attached:
#   1. AWS-managed AWSLambdaBasicExecutionRole — grants the Lambda permission
#      to write to its own CloudWatch log group. This is what makes the webhook
#      firing observable: every invocation logs Start/End/Report lines plus our
#      `print(json.dumps({"event": "okta_hook_processed", ...}))` from handler.py.
#   2. Inline policy granting GetSecretValue on EXACTLY the two secret ARNs.
#      Least-privilege: this Lambda cannot read any other secrets in the account.

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
  description        = "Execution role for the Okta event hook Lambda."
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
      aws_secretsmanager_secret.okta_webhook_secret.arn,
      aws_secretsmanager_secret.slack_bot_token.arn,
      aws_secretsmanager_secret.okta_api_client_id.arn,
      aws_secretsmanager_secret.okta_api_key_id.arn,
      aws_secretsmanager_secret.okta_api_private_key.arn,
    ]
  }
}

resource "aws_iam_role_policy" "secrets_read" {
  name   = "${var.name_prefix}-secrets-read"
  role   = aws_iam_role.lambda_exec.id
  policy = data.aws_iam_policy_document.secrets_read.json
}
