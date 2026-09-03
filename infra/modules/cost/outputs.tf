output "cost_ingestion_worker_function_name" {
  value = aws_lambda_function.cost_ingestion_worker.function_name
}

output "cost_ingestion_worker_function_arn" {
  value = aws_lambda_function.cost_ingestion_worker.arn
}

output "notification_worker_function_name" {
  value = aws_lambda_function.notification_worker.function_name
}

output "notification_worker_function_arn" {
  value = aws_lambda_function.notification_worker.arn
}
