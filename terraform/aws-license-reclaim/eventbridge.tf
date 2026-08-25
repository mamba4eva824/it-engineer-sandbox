# EventBridge rule on leaver.completed → scanner Lambda.
# maximum_retry_attempts = 2; SQS DLQ for exhausted invokes (P2-R2).

resource "aws_sqs_queue" "scanner_dlq" {
  name                      = "ohmgym-license-scanner-dlq"
  message_retention_seconds = 1209600
}

resource "aws_cloudwatch_event_rule" "leaver_completed" {
  name        = "${var.name_prefix}-leaver-completed"
  description = "Invoke the license scanner after a successful Okta deactivate."

  event_pattern = jsonencode({
    source        = ["ohmgym.offboarding"]
    "detail-type" = ["leaver.completed"]
  })
}

data "aws_iam_policy_document" "scanner_dlq" {
  statement {
    sid    = "AllowEventBridge"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.scanner_dlq.arn]
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.leaver_completed.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "scanner_dlq" {
  queue_url = aws_sqs_queue.scanner_dlq.id
  policy    = data.aws_iam_policy_document.scanner_dlq.json
}

resource "aws_cloudwatch_event_target" "scanner" {
  rule = aws_cloudwatch_event_rule.leaver_completed.name
  arn  = aws_lambda_function.license_scanner.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }

  dead_letter_config {
    arn = aws_sqs_queue.scanner_dlq.arn
  }
}

resource "aws_lambda_permission" "allow_eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.license_scanner.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.leaver_completed.arn
}

# -----------------------------------------------------------------------------
# Orchestrator: license.scan.complete → orchestrator Lambda
# retries = 2; SQS DLQ (same pattern as the scanner rule above).
#
# AWS provider 5.x has no per-target is_enabled. Rule is_enabled tracks
# var.enable_orchestrator so this target does not fire while HITL is default.
# The Lambda is still deployed for CLI invoke.
# -----------------------------------------------------------------------------

resource "aws_sqs_queue" "orchestrator_dlq" {
  name                      = "${var.orchestrator_name_prefix}-dlq"
  message_retention_seconds = 1209600
}

resource "aws_cloudwatch_event_rule" "orchestrator_scan_complete" {
  name        = "${var.orchestrator_name_prefix}-scan-complete"
  description = "Invoke the license reclaim orchestrator after a ticketed or partial scan."
  is_enabled  = var.enable_orchestrator

  event_pattern = jsonencode({
    source        = ["ohmgym.licenses"]
    "detail-type" = ["license.scan.complete"]
  })
}

data "aws_iam_policy_document" "orchestrator_dlq" {
  statement {
    sid    = "AllowEventBridge"
    effect = "Allow"
    principals {
      type        = "Service"
      identifiers = ["events.amazonaws.com"]
    }
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.orchestrator_dlq.arn]
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_cloudwatch_event_rule.orchestrator_scan_complete.arn]
    }
  }
}

resource "aws_sqs_queue_policy" "orchestrator_dlq" {
  queue_url = aws_sqs_queue.orchestrator_dlq.id
  policy    = data.aws_iam_policy_document.orchestrator_dlq.json
}

resource "aws_cloudwatch_event_target" "orchestrator" {
  rule = aws_cloudwatch_event_rule.orchestrator_scan_complete.name
  arn  = aws_lambda_function.license_reclaim_orchestrator.arn

  retry_policy {
    maximum_event_age_in_seconds = 3600
    maximum_retry_attempts       = 2
  }

  dead_letter_config {
    arn = aws_sqs_queue.orchestrator_dlq.arn
  }
}

resource "aws_lambda_permission" "allow_eventbridge_orchestrator" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.license_reclaim_orchestrator.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.orchestrator_scan_complete.arn
}
