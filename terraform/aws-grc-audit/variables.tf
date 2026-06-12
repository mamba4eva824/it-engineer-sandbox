variable "aws_region" {
  description = "AWS region for DynamoDB tables and IAM resources."
  type        = string
  default     = "us-west-1"
}

variable "name_prefix" {
  description = "Prefix for IAM role and policy names."
  type        = string
  default     = "ohmgym-grc-jml-audit"
}

variable "onboarding_table_name" {
  description = "Onboarding audit DynamoDB table."
  type        = string
  default     = "ohmgym-onboarding-logs"
}

variable "offboarding_table_name" {
  description = "Offboarding audit DynamoDB table."
  type        = string
  default     = "ohmgym-offboarding-logs"
}

variable "trusted_principal_arns" {
  description = "IAM principal ARNs allowed to assume the GRC audit read role (e.g. website-admin user)."
  type        = list(string)
  default     = []
}

variable "identity_center_instance_arn" {
  description = "IAM Identity Center instance ARN. Leave empty when Identity Center is not enabled."
  type        = string
  default     = ""
}

variable "identity_store_id" {
  description = "Identity Store ID (d-xxxxxxxxxx). Required when identity_center_instance_arn is set."
  type        = string
  default     = ""
}

variable "sso_target_account_id" {
  description = "AWS account ID for SSO account assignments."
  type        = string
  default     = ""
}

variable "sso_user_emails" {
  description = "Emails of GRC users to provision in Identity Store and assign JMLAuditReadOnly."
  type        = list(string)
  default = [
    "bryan.wong@ohmgym.com",
    "weinreichchris@gmail.com",
  ]
}

variable "tags" {
  description = "Default tags applied by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "grc-jml-audit"
    ManagedBy = "terraform"
    Owner     = "grc"
  }
}
