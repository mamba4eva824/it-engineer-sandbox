# Input variables for the shared ohmgym-jml Secrets Manager stack.

variable "aws_region" {
  description = "AWS region for all secrets (us-west-1 — colocated with JML Lambdas)."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix for secret names, e.g. ohmgym-jml/slack-bot-token."
  type        = string
  default     = "ohmgym-jml"
}

variable "tags" {
  description = "Default tags applied to every resource by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "jml-secrets"
    ManagedBy = "terraform"
    Owner     = "it-ops"
  }
}

variable "okta_webhook_secret" {
  description = "Shared secret Okta sends in the Authorization header on event hook POSTs."
  type        = string
  sensitive   = true
}

variable "slack_bot_token" {
  description = "Slack xoxb- bot token for joiner/leaver channel posts."
  type        = string
  sensitive   = true
}

variable "okta_api_client_id" {
  description = "Okta API Services app client id. Same as OKTA_CLIENT_ID in .env."
  type        = string
  sensitive   = true
}

variable "okta_api_key_id" {
  description = "Okta API Services app key id (kid). Same as OKTA_KEY_ID in .env."
  type        = string
  sensitive   = true
}

variable "okta_api_private_key" {
  description = "PEM private key for the Okta API Services app. Same as OKTA_PRIVATE_KEY in .env."
  type        = string
  sensitive   = true
}
