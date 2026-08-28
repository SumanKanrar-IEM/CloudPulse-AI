output "compliance_validation_queue_url" {
  description = "Consumed by infra/modules/scan as the scan-worker Lambda's enqueue target (T026, research.md R-303)."
  value       = aws_sqs_queue.compliance_validation.id
}

output "compliance_validation_queue_arn" {
  description = "Consumed by infra/modules/scan to grant the scan-worker sqs:SendMessage (T026)."
  value       = aws_sqs_queue.compliance_validation.arn
}

output "ownership_attribution_queue_url" {
  value = aws_sqs_queue.ownership_attribution.id
}

output "ownership_attribution_queue_arn" {
  value = aws_sqs_queue.ownership_attribution.arn
}

output "compliance_validation_dlq_name" {
  description = "For infra/modules/observability's dlq_names list (P2, not wired by this spec's P1 scope)."
  value       = aws_sqs_queue.compliance_validation_dlq.name
}

output "ownership_attribution_dlq_name" {
  value = aws_sqs_queue.ownership_attribution_dlq.name
}
