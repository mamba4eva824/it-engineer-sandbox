# Audit trail for license-scan findings.
#
# One row per (run_date, user_id). Scanner does GetItem + PutItem only.
# Phase 3 broker adds Query (via the jira_issue_key GSI below) + UpdateItem
# on its own dedicated role (broker_iam.tf) — the scanner role is untouched.
# PAY_PER_REQUEST matches the offboarding logs table. TTL on ttl_epoch
# (90 days).
#
# GSI on jira_issue_key: the JSM ticket stores okta_user_id and
# offboarding_run_id (a random batch UUID) but not run_date, so the broker
# cannot reconstruct the table's primary key from a ticket key alone. This
# index lets it look up the finding row directly by issue_key.

resource "aws_dynamodb_table" "license_reclaim_logs" {
  name         = var.dynamodb_table_name
  billing_mode = "PAY_PER_REQUEST"

  hash_key  = "run_date"
  range_key = "user_id"

  attribute {
    name = "run_date"
    type = "S"
  }

  attribute {
    name = "user_id"
    type = "S"
  }

  attribute {
    name = "jira_issue_key"
    type = "S"
  }

  global_secondary_index {
    name            = "jira_issue_key-index"
    hash_key        = "jira_issue_key"
    projection_type = "ALL"
  }

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
