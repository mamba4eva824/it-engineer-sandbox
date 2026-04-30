# Input variables for the Okta-event-hook → Slack Lambda stack.
#
# Sensitive values (slack_bot_token, okta_webhook_secret) live in a gitignored
# terraform.tfvars; copy terraform.tfvars.example to terraform.tfvars and fill
# them in. Plan/apply marks them sensitive so they don't appear in CLI output
# or in CI logs.

variable "aws_region" {
  description = "AWS region for all resources."
  type        = string
  default     = "us-east-1"
}

variable "name_prefix" {
  description = "Prefix applied to every resource name (lambda, secrets, IAM)."
  type        = string
  default     = "novatech-okta-hook"
}

variable "tags" {
  description = "Default tags applied to every resource by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "okta-event-hook"
    ManagedBy = "terraform"
    Owner     = "it-ops"
  }
}

variable "okta_webhook_secret" {
  description = "Shared secret Okta sends in the Authorization header on every event POST."
  type        = string
  sensitive   = true
}

variable "slack_bot_token" {
  description = "Slack xoxb- bot token; the Lambda uses it to post to #joiner-it-ops."
  type        = string
  sensitive   = true
}

variable "slack_team_id" {
  description = "Slack workspace team_id (T-prefix), needed for org-installed bot to call conversations.create."
  type        = string
  default     = "T0AUHDULU9Z"
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
