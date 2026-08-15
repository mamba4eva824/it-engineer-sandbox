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

variable "license_reclaim_table_name" {
  description = "License reclaim audit DynamoDB table."
  type        = string
  default     = "ohmgym-license-reclaim-logs"
}

variable "trusted_principal_arns" {
  description = "IAM principal ARNs allowed to assume the GRC audit read role (e.g. website-admin user)."
  type        = list(string)
  default     = []
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
