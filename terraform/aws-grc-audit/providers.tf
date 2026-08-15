# Provider + Terraform version pinning for the ohmgym-grc-jml-audit stack.
#
# Grants GRC analysts read-only DynamoDB access to JML onboarding/offboarding
# and license-reclaim audit tables. Uses a standalone IAM role when IAM
# Identity Center is not enabled; optional SSO permission set resources
# activate when instance ARN is set.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
