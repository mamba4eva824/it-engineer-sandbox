# Shared JML secrets — us-west-1 only (no cross-region replicas).
#
# Consumed by ohmgym-activation-workflow, ohmgym-onboarding-workflow, and
# ohmgym-offboarding-workflow. State is local for now (Phase 7 remote state).

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
