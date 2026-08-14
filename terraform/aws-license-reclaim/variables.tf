# Input variables for the ohmgym-license-scanner stack.
#
# Sensitive inputs (Slack secret ARN + alarm email) live in a gitignored
# terraform.tfvars. License read/write secret *shells* are created here;
# operators put values from the project .env after apply.

variable "aws_region" {
  description = "AWS region for all resources in this stack (us-west-1)."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix applied to every resource name (lambda, log group, IAM, alarms)."
  type        = string
  default     = "ohmgym-license-scanner"
}

variable "dynamodb_table_name" {
  description = "Audit-trail table that records every license-scan attempt."
  type        = string
  default     = "ohmgym-license-reclaim-logs"
}

variable "tags" {
  description = "Default tags applied to every resource by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "license-scanner"
    ManagedBy = "terraform"
    Owner     = "it-ops"
  }
}

variable "slack_bot_token_secret_arn" {
  description = "ARN for ohmgym-jml/slack-bot-token (shared with offboarding)."
  type        = string
}

variable "slack_bot_token_secret_name" {
  type    = string
  default = "ohmgym-jml/slack-bot-token"
}

variable "github_org" {
  type    = string
  default = "ohmgym-sandbox"
}

variable "jira_cloud_id" {
  description = "Atlassian cloudId for gateway calls (api.atlassian.com/ex/jira/{id})."
  type        = string
  default     = "359c6979-fbf2-459e-b948-9feb032a082e"
}

variable "jira_email" {
  description = "Atlassian account email used as Basic-auth username for Jira REST."
  type        = string
}

variable "jira_project_key" {
  type    = string
  default = "SUP"
}

variable "jira_request_type_id" {
  type    = string
  default = "4"
}

variable "jira_issue_type_id" {
  type    = string
  default = "10079"
}

variable "linear_org_uuid" {
  type    = string
  default = "2cb9e2d3-f42b-42a1-a066-8bc4006c2624"
}

variable "slack_team_id" {
  type    = string
  default = "T0AUHDULU9Z"
}

variable "leaver_channel_name" {
  type    = string
  default = "leaver-it-ops"
}

variable "lambda_log_retention_days" {
  type    = number
  default = 14
}

variable "dynamodb_ttl_days" {
  type    = number
  default = 90
}

variable "lambda_memory_mb" {
  type    = number
  default = 512
}

variable "lambda_timeout_seconds" {
  description = "Lambda timeout in seconds. 120s covers 3 apps × retries × 15s."
  type        = number
  default     = 120
}

variable "alarm_email" {
  description = "Email endpoint for the CloudWatch error alarm."
  type        = string
}
