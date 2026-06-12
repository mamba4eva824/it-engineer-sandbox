# Input variables for the ohmgym-activation-workflow (reactive joiner) stack.
#
# Secret values live in terraform/aws-secrets/. This stack references ARNs only.

variable "aws_region" {
  description = "AWS region for all resources (us-west-1 — colocated with JML secrets)."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix applied to every resource name (lambda, IAM, log group)."
  type        = string
  default     = "ohmgym-activation-workflow"
}

variable "tags" {
  description = "Default tags applied to every resource by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "activation-workflow"
    ManagedBy = "terraform"
    Owner     = "it-ops"
  }
}

variable "slack_team_id" {
  description = "Slack workspace team_id (T-prefix), needed for org-installed bot to call conversations.create."
  type        = string
  default     = "T0AUHDULU9Z"
}

variable "okta_org_url" {
  description = "Okta tenant base URL — used by the Lambda's dedup lookup."
  type        = string
}

variable "joiner_channel_name" {
  description = "Slack public channel the activation message posts to."
  type        = string
  default     = "joiner-it-ops"
}

variable "lambda_log_retention_days" {
  description = "CloudWatch log retention for the Lambda's log group."
  type        = number
  default     = 14
}

# Secret ARNs from terraform/aws-secrets outputs (us-west-1).
variable "slack_bot_token_secret_arn" {
  description = "ARN for ohmgym-jml/slack-bot-token."
  type        = string
}

variable "okta_api_client_id_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-client-id."
  type        = string
}

variable "okta_api_key_id_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-key-id."
  type        = string
}

variable "okta_api_private_key_secret_arn" {
  description = "ARN for ohmgym-jml/okta-api-private-key."
  type        = string
}

variable "okta_webhook_secret_arn" {
  description = "ARN for ohmgym-jml/okta-webhook-secret."
  type        = string
}

# Secret names passed to Lambda env vars (GetSecretValue by name).
variable "slack_bot_token_secret_name" {
  type    = string
  default = "ohmgym-jml/slack-bot-token"
}

variable "okta_api_client_id_secret_name" {
  type    = string
  default = "ohmgym-jml/okta-api-client-id"
}

variable "okta_api_key_id_secret_name" {
  type    = string
  default = "ohmgym-jml/okta-api-key-id"
}

variable "okta_api_private_key_secret_name" {
  type    = string
  default = "ohmgym-jml/okta-api-private-key"
}

variable "okta_webhook_secret_name" {
  type    = string
  default = "ohmgym-jml/okta-webhook-secret"
}
