# CloudWatch alarm + SNS email subscription for Lambda errors.
#
# A daily automation has no statistical headroom — one error per day IS
# the population. The alarm fires on a single Errors >= 1 datapoint in a
# 5-minute period. Missing data is "notBreaching" because the metric only
# has data after invocations; otherwise the alarm goes INSUFFICIENT_DATA
# permanently.
#
# Email subscription requires manual confirmation — AWS sends a one-time
# link to var.alarm_email on first apply; click it.

resource "aws_sns_topic" "alarms" {
  name = "${var.name_prefix}-alarms"
}

resource "aws_sns_topic_subscription" "alarms_email" {
  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = var.alarm_email
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.name_prefix}-errors"
  alarm_description   = "Fires when the onboarding workflow Lambda records any error in a 5-minute window."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  datapoints_to_alarm = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = aws_lambda_function.onboarding_workflow.function_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]
}
