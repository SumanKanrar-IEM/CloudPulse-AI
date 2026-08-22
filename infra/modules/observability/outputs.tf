output "alerts_topic_arn" {
  description = "Alarms publish here; the email subscription delivers (FR-051)."
  value       = aws_sns_topic.alerts.arn
}

output "dashboard_name" {
  value = aws_cloudwatch_dashboard.this.dashboard_name
}

output "alarm_names" {
  description = "Every alarm, so test_alarm_wiring.sh can assert each has an SNS action."
  value = concat(
    [
      aws_cloudwatch_metric_alarm.api_errors.alarm_name,
      aws_cloudwatch_metric_alarm.scan_failures.alarm_name,
      aws_cloudwatch_metric_alarm.alerting_heartbeat.alarm_name,
    ],
    [for a in aws_cloudwatch_metric_alarm.dlq_depth : a.alarm_name],
  )
}

output "email_subscription_pending" {
  description = "AWS requires the recipient to confirm by email. Until then, alerting is inert."
  value       = var.alert_email != ""
}
