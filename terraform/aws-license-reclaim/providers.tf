# Provider + Terraform version pinning for the ohmgym license scanner stack.
#
# Region is us-west-1 — colocated with terraform/aws-secrets (ohmgym-jml/*)
# and terraform/aws-offboarding.
#
# State is local for now.

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.70"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.5"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = var.tags
  }
}
