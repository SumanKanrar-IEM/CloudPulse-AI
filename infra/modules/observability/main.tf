# Observability — dashboard and alarms (S7, FR-049 to FR-053). **P2 / STRETCH.**
#
# Per constitution Principle VIII and spec §US7, nothing here may block or destabilise a
# P1 path. Deleting this module entirely leaves every P1 success criterion satisfied.
#
# FR-050 left the thresholds as "agreed threshold". T116 decides them, and the reasoning
# is recorded here rather than in a commit message so the next person can tell a
# considered value from an arbitrary one.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

locals {
  name = "cloudpulse-${var.environment}"
}

# --- Alert delivery (FR-051) ----------------------------------------------

resource "aws_sns_topic" "alerts" {
  name = "${local.name}-alerts"
}

resource "aws_sns_topic_subscription" "email" {
  count = var.alert_email == "" ? 0 : 1

  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email

  # AWS sends a confirmation email; the subscription is inert until someone clicks it.
  # Terraform cannot confirm on your behalf, so a fresh environment has a pending
  # subscription until a human accepts. Called out because a silent pending
  # subscription looks exactly like working alerting until the first real incident.
}

# --- Alarms (FR-050, FR-052) ----------------------------------------------
#
# Every alarm sets `treat_missing_data`. The default ("missing") means an alarm with no
# data sits in INSUFFICIENT_DATA and never fires — which for a failure-count metric is
# indistinguishable from healthy. Each choice below is deliberate.

# FR-050: service errors above the agreed threshold.
#
# Threshold reasoning (T116): 5 server errors in 5 minutes, sustained for 2 periods.
# At demo scale (~10 concurrent users) a healthy service produces zero 5xx, so any
# sustained non-zero rate is real. Two periods rather than one avoids paging on a
# single cold-start blip; 5 rather than 1 avoids paging on one user hitting one bug.
resource "aws_cloudwatch_metric_alarm" "api_errors" {
  alarm_name        = "${local.name}-api-5xx"
  alarm_description = "API 5xx rate above threshold (FR-050)."

  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = var.api_id }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.api_error_threshold
  comparison_operator = "GreaterThanOrEqualToThreshold"

  # No traffic means no errors. For an error COUNT, missing data is genuinely good.
  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  # FR-052: returns to healthy on its own when the condition clears.
  ok_actions = [aws_sns_topic.alerts.arn]
}

# FR-050: a scan fails. Populated by spec 002's custom metric.
#
# Threshold reasoning (T116): 1 failure in 15 minutes. Unlike an error rate, a failed
# scan is never acceptable — a single one means an account went unscanned, so there is
# no "tolerable rate" to tune.
resource "aws_cloudwatch_metric_alarm" "scan_failures" {
  alarm_name        = "${local.name}-scan-failed"
  alarm_description = "One or more discovery scans failed (FR-050)."

  namespace           = "CloudPulse"
  metric_name         = "ScanFailed"
  dimensions          = { Environment = var.environment }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# FR-050: work accumulating in a dead-letter queue.
#
# Threshold reasoning (T116): any message at all, evaluated over 5 minutes. A DLQ is by
# definition where work goes when it could not be processed — a non-zero depth is
# already the failure, so there is nothing to tolerate.
resource "aws_cloudwatch_metric_alarm" "dlq_depth" {
  for_each = toset(var.dlq_names)

  alarm_name        = "${local.name}-dlq-${each.value}"
  alarm_description = "Messages accumulating in the ${each.value} dead-letter queue (FR-050)."

  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = each.value }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"

  treat_missing_data = "notBreaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

# --- FR-053: the alerting path's own failure must be visible ---------------
#
# This is the alarm that makes the others trustworthy. Without it, silence has two
# possible meanings — "nothing is wrong" and "alerting is broken" — and they are
# indistinguishable. A heartbeat inverts that: the canary Lambda emits a metric on a
# schedule, and the alarm fires when the metric STOPS arriving.
#
# Note the inversion in `treat_missing_data`: here missing data is the whole point, so
# it is "breaching" rather than "notBreaching".
resource "aws_cloudwatch_metric_alarm" "alerting_heartbeat" {
  alarm_name        = "${local.name}-alerting-heartbeat"
  alarm_description = "The alerting path stopped reporting. Silence may not mean health (FR-053)."

  namespace           = "CloudPulse"
  metric_name         = "AlertingHeartbeat"
  dimensions          = { Environment = var.environment }
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"

  # Inverted deliberately: a missing heartbeat IS the failure.
  treat_missing_data = "breaching"

  alarm_actions = [aws_sns_topic.alerts.arn]
  ok_actions    = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_event_rule" "heartbeat" {
  name                = "${local.name}-heartbeat"
  description         = "Emits the alerting heartbeat metric (FR-053)."
  schedule_expression = "rate(5 minutes)"
}

# --- Dashboard (FR-049) ----------------------------------------------------

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = local.name

  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title  = "API errors and latency"
          region = var.aws_region
          metrics = [
            ["AWS/ApiGateway", "5xx", "ApiId", var.api_id, { stat = "Sum" }],
            [".", "4xx", ".", ".", { stat = "Sum" }],
            [".", "Latency", ".", ".", { stat = "p95" }],
          ]
          period = 300
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Scan outcomes"
          region = var.aws_region
          metrics = [
            ["CloudPulse", "ScanSucceeded", "Environment", var.environment, { stat = "Sum" }],
            [".", "ScanFailed", ".", ".", { stat = "Sum" }],
          ]
          period = 900
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title   = "Dead-letter queue depth"
          region  = var.aws_region
          metrics = [for q in var.dlq_names : ["AWS/SQS", "ApproximateNumberOfMessagesVisible", "QueueName", q]]
          period  = 300
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title   = "Alerting heartbeat (FR-053)"
          region  = var.aws_region
          metrics = [["CloudPulse", "AlertingHeartbeat", "Environment", var.environment, { stat = "Sum" }]]
          period  = 900
        }
      },
    ]
  })
}
