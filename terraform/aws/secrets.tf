# Two Secrets Manager entries the Lambda reads at cold-start.
#
# Why Secrets Manager and not Lambda env vars: env vars are visible to anyone
# with lambda:GetFunctionConfiguration; Secrets Manager requires the explicit
# secretsmanager:GetSecretValue scoped to a specific ARN (granted in iam.tf).
# This lets us audit secret access via CloudTrail and rotate without touching
# the function configuration.
#
# Both secrets store the value as a plain string (not JSON), matching how
# handler.py reads them: `_secrets_client.get_secret_value(SecretId=name)["SecretString"]`.

resource "aws_secretsmanager_secret" "okta_webhook_secret" {
  name                    = "${var.name_prefix}/okta-webhook-secret"
  description             = "Shared secret Okta sends as the Authorization header on event hook POSTs."
  recovery_window_in_days = 0 # immediate delete on terraform destroy (sandbox; production would be 7-30)
}

resource "aws_secretsmanager_secret_version" "okta_webhook_secret" {
  secret_id     = aws_secretsmanager_secret.okta_webhook_secret.id
  secret_string = var.okta_webhook_secret
}

resource "aws_secretsmanager_secret" "slack_bot_token" {
  name                    = "${var.name_prefix}/slack-bot-token"
  description             = "Slack xoxb- bot token used by the Lambda to post to #joiner-it-ops."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "slack_bot_token" {
  secret_id     = aws_secretsmanager_secret.slack_bot_token.id
  secret_string = var.slack_bot_token
}
