output "agent_runtime_arn" {
  value       = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
  description = "The one runtime every capability runs on. Passed to the digest and suggester workers so they invoke the runtime this module created rather than one named by hand."
}

output "agent_runtime_id" {
  value = aws_bedrockagentcore_agent_runtime.this.agent_runtime_id
}

output "agent_artifacts_bucket" {
  value = aws_s3_bucket.agent_artifacts.id
}

output "digest_worker_function_name" {
  value = aws_lambda_function.digest_worker.function_name
}

output "suggester_worker_function_name" {
  value = aws_lambda_function.suggester_worker.function_name
}

output "advisor_worker_function_name" {
  value = aws_lambda_function.advisor_worker.function_name
}

output "metrics_collector_function_name" {
  value = aws_lambda_function.metrics_collector.function_name
}
