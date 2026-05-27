# EventBridge Scheduler — the modern primitive for cron-based Lambda invokes.
#
# Pinned to America/Los_Angeles so the cron expression survives DST without
# manual UTC math. 5:00 PM PT every day. No retries on the scheduler side —
# the Lambda's DynamoDB idempotency guard + the replay CLI handle recovery.
#
# This is NOT aws_cloudwatch_event_rule (the legacy primitive) — the legacy
# rule only accepts UTC and lacks the timezone field.

resource "aws_scheduler_schedule" "daily" {
  name        = var.name_prefix
  description = "Daily offboarding-workflow trigger at 5:00 PM America/Los_Angeles."

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression          = var.schedule_cron
  schedule_expression_timezone = var.schedule_timezone

  target {
    arn      = aws_lambda_function.offboarding_workflow.arn
    role_arn = aws_iam_role.scheduler.arn

    retry_policy {
      maximum_event_age_in_seconds = 300
      maximum_retry_attempts       = 0
    }
  }
}
