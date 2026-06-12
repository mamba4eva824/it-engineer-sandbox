# Input variables for the ohmgym-onboarding-workflow stack.
#
# Sensitive inputs (the 4 secret ARNs from terraform/aws-secrets outputs, and alarm email)
# live in a gitignored terraform.tfvars.

variable "aws_region" {
  description = "AWS region for all resources in this stack (us-west-1)."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix applied to every resource name (lambda, log group, IAM, scheduler, alarms)."
  type        = string
  default     = "ohmgym-onboarding-workflow"
}

variable "dynamodb_table_name" {
  description = "Audit-trail table that records every activation attempt."
  type        = string
  default     = "ohmgym-onboarding-logs"
}

variable "tags" {
  description = "Default tags applied to every resource by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "onboarding-workflow"
    ManagedBy = "terraform"
    Owner     = "it-ops"
  }
}

# Secret ARNs from terraform/aws-secrets (us-west-1 primaries).
variable "slack_bot_token_secret_arn" {
  description = "ARN for ohmgym-jml/slack-bot-token (terraform/aws-secrets output)."
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

variable "slack_bot_token_secret_name" {
  description = "Secret name for GetSecretValue (no ARN suffix)."
  type        = string
  default     = "ohmgym-jml/slack-bot-token"
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

variable "okta_org_url" {
  description = "Okta tenant base URL, e.g. https://integrator-2367542.okta.com."
  type        = string
}

variable "slack_team_id" {
  description = "Slack workspace team_id (T-prefix) — required for org-installed bot to call conversations.create."
  type        = string
  default     = "T0AUHDULU9Z"
}

variable "joiner_channel_name" {
  description = "Slack public channel the batch-summary message posts to."
  type        = string
  default     = "joiner-it-ops"
}

variable "lambda_log_retention_days" {
  description = "CloudWatch log retention for the Lambda's log group."
  type        = number
  default     = 14
}

variable "dynamodb_ttl_days" {
  description = "Days the audit-trail rows persist before DynamoDB TTL auto-purges them."
  type        = number
  default     = 90
}

variable "lambda_memory_mb" {
  description = "Lambda memory size in MB."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds."
  type        = number
  default     = 60
}

variable "schedule_cron" {
  description = "EventBridge Scheduler cron expression in `cron(...)` form. 9am daily by default."
  type        = string
  default     = "cron(0 9 * * ? *)"
}

variable "schedule_timezone" {
  description = "IANA timezone for the cron expression. America/Los_Angeles handles DST correctly."
  type        = string
  default     = "America/Los_Angeles"
}

variable "alarm_email" {
  description = "Email endpoint for the CloudWatch error alarm. SNS will send a one-time confirmation link on first apply."
  type        = string
}
