# Provider + Terraform version pinning for the ohmgym-onboarding-workflow stack.
#
# Region is us-west-1 — deliberate isolation from the existing us-east-1
# novatech-okta-hook stack (terraform/aws/). The 4 Secrets Manager entries
# this Lambda reads are native us-west-1 replicas (set up in
# terraform/aws/secrets.tf via the `replica { region = "us-west-1" }` block).
#
# State is local for now. Phase 7 of the roadmap moves both AWS roots to
# S3 + DynamoDB remote state together.

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
