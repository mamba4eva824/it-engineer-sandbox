# Input variables for the ohmgym-onboarding-workflow stack.
#
# Sensitive inputs (the 4 replica ARNs the operator copies from terraform/aws
# outputs, and the alarm email) live in a gitignored terraform.tfvars.

variable "aws_region" {
  description = "AWS region for all resources in this stack. Pinned to us-west-1 for isolation from the existing us-east-1 stack."
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

# Replica ARNs from the us-east-1 stack. After `terraform -chdir=terraform/aws apply`,
# copy the four `*_replica_arn_us_west_1` outputs into terraform.tfvars.
variable "slack_bot_token_replica_arn" {
  description = "us-west-1 replica ARN for the Slack bot token (from terraform/aws output slack_bot_token_replica_arn_us_west_1)."
  type        = string
}

variable "okta_api_client_id_replica_arn" {
  description = "us-west-1 replica ARN for the Okta API client id."
  type        = string
}

variable "okta_api_key_id_replica_arn" {
  description = "us-west-1 replica ARN for the Okta API key id."
  type        = string
}

variable "okta_api_private_key_replica_arn" {
  description = "us-west-1 replica ARN for the Okta API private key (PEM)."
  type        = string
}

# Replica secret NAMES (used as env vars for the Lambda's SecretsManager GetSecretValue calls).
# These match the suffix-less form: secret arn has the 6-char suffix; the name does not.
variable "slack_bot_token_secret_name" {
  description = "Secret name (without ARN suffix) for the Slack bot token replica."
  type        = string
  default     = "novatech-okta-hook/slack-bot-token"
}

variable "okta_api_client_id_secret_name" {
  description = "Secret name for the Okta API client id replica."
  type        = string
  default     = "novatech-okta-hook/okta-api-client-id"
}

variable "okta_api_key_id_secret_name" {
  description = "Secret name for the Okta API key id replica."
  type        = string
  default     = "novatech-okta-hook/okta-api-key-id"
}

variable "okta_api_private_key_secret_name" {
  description = "Secret name for the Okta API private key replica."
  type        = string
  default     = "novatech-okta-hook/okta-api-private-key"
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
