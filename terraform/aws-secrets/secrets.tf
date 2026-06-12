# Five plain-string secrets read at Lambda cold-start by all three JML workflows.
# No replica blocks — single-region primaries in us-west-1.

resource "aws_secretsmanager_secret" "okta_webhook_secret" {
  name                    = "${var.name_prefix}/okta-webhook-secret"
  description             = "Authorization header secret for Okta event hook POSTs (activation workflow only)."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "okta_webhook_secret" {
  secret_id     = aws_secretsmanager_secret.okta_webhook_secret.id
  secret_string = var.okta_webhook_secret
}

resource "aws_secretsmanager_secret" "slack_bot_token" {
  name                    = "${var.name_prefix}/slack-bot-token"
  description             = "Slack xoxb- bot token for #joiner-it-ops and #leaver-it-ops."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "slack_bot_token" {
  secret_id     = aws_secretsmanager_secret.slack_bot_token.id
  secret_string = var.slack_bot_token
}

resource "aws_secretsmanager_secret" "okta_api_client_id" {
  name                    = "${var.name_prefix}/okta-api-client-id"
  description             = "Okta API Services app client id."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "okta_api_client_id" {
  secret_id     = aws_secretsmanager_secret.okta_api_client_id.id
  secret_string = var.okta_api_client_id
}

resource "aws_secretsmanager_secret" "okta_api_key_id" {
  name                    = "${var.name_prefix}/okta-api-key-id"
  description             = "Okta API Services app key id (kid)."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "okta_api_key_id" {
  secret_id     = aws_secretsmanager_secret.okta_api_key_id.id
  secret_string = var.okta_api_key_id
}

resource "aws_secretsmanager_secret" "okta_api_private_key" {
  name                    = "${var.name_prefix}/okta-api-private-key"
  description             = "PEM-encoded private key for the Okta API Services app."
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "okta_api_private_key" {
  secret_id     = aws_secretsmanager_secret.okta_api_private_key.id
  secret_string = var.okta_api_private_key
}
