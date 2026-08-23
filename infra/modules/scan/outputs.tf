output "state_machine_arn" {
  description = "Consumed by infra/modules/api so the on-demand-trigger endpoint (T048) can start executions."
  value       = local.scan_state_machine_arn
}

output "worker_function_name" {
  value = aws_lambda_function.worker.function_name
}

output "worker_function_arn" {
  value = aws_lambda_function.worker.arn
}
