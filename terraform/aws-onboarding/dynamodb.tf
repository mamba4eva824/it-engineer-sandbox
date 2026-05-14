# Audit trail for the daily onboarding batch.
#
# One row per (run_date, user_id) — the partition key colocates a single
# day's batch for a Query-by-run_date lookup; the sort key enforces
# per-user-per-day idempotency. PutItem + GetItem are the only operations
# the Lambda performs; PAY_PER_REQUEST is the right billing model for a
# table that sees < 30 writes/day.
#
# TTL on `ttl_epoch` auto-purges rows after `dynamodb_ttl_days` days. Lambda
# sets the value when it writes; AWS sweeps within ~48h after expiry.

resource "aws_dynamodb_table" "onboarding_logs" {
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
    enabled = false # sandbox; production would enable
  }
}
