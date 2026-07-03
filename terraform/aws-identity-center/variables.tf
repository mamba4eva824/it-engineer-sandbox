variable "aws_region" {
  description = "IAM Identity Center home region."
  type        = string
  default     = "us-west-1"
}

variable "identity_center_instance_arn" {
  description = "IAM Identity Center instance ARN (ssoins-...)."
  type        = string
}

variable "identity_store_id" {
  description = "Identity Store ID (d-...)."
  type        = string
}

variable "target_account_id" {
  description = "AWS account ID receiving permission set assignments."
  type        = string
  default     = "430118826061"
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
