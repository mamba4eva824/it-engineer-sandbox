# Provider + Terraform version pinning.
#
# Region is us-east-1 to match the existing AWS profile (account 430118826061).
# State is local for now — Phase 5 of the roadmap will move to S3 + DynamoDB
# remote state once a second engineer joins the project.
#
# `local_file` (built into Terraform's local provider) reads the external
# Lambda zip so source_code_hash detects code changes and re-deploys.

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
