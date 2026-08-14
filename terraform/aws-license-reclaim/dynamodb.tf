# Audit trail for license-scan findings.
#
# One row per (run_date, user_id). GetItem + PutItem only. PAY_PER_REQUEST
# matches the offboarding logs table. TTL on ttl_epoch (90 days).

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

  ttl {
    attribute_name = "ttl_epoch"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = false
  }
}
