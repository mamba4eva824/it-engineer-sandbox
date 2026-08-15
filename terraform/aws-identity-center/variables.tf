variable "aws_region" {
  description = "IAM Identity Center home region."
  type        = string
  default     = "us-west-1"
}

variable "identity_center_instance_arn" {
  description = "IAM Identity Center instance ARN (ssoins-...). Leave empty to auto-detect from the provider region."
  type        = string
  default     = ""

  validation {
    condition     = var.identity_center_instance_arn == "" || can(regex("^arn:aws:sso:::instance/", var.identity_center_instance_arn))
    error_message = "Must be an IAM Identity Center instance ARN or empty to auto-detect."
  }
}

variable "identity_store_id" {
  description = "Identity Store ID (d-...). Leave empty to auto-detect from the provider region."
  type        = string
  default     = ""

  validation {
    condition     = var.identity_store_id == "" || can(regex("^d-[a-z0-9]+$", var.identity_store_id))
    error_message = "Must be an Identity Store ID (d-xxxxxxxxxx) or empty to auto-detect."
  }
}

variable "target_account_id" {
  description = "AWS account ID receiving permission set assignments."
  type        = string
  default     = "882248517627"
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

variable "developer_user_emails" {
  description = "Emails provisioned in Identity Store and added to the Developers group."
  type        = list(string)
  default     = []
}

variable "grc_user_emails" {
  description = "Emails provisioned in Identity Store and added to the GRC group."
  type        = list(string)
  default = [
    "weinreichchris@gmail.com",
  ]
}

variable "tags" {
  description = "Default tags applied by the AWS provider."
  type        = map(string)
  default = {
    Project   = "IT-Operations-Sandbox"
    Component = "identity-center"
    ManagedBy = "terraform"
  }
}
