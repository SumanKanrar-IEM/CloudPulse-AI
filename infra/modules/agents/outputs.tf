output "digest_agent_id" {
  value       = aws_bedrockagent_agent.digest.agent_id
  description = "Passed to the digest worker so it invokes the agent this module created rather than one named by hand."
}

output "digest_agent_alias_id" {
  value       = aws_bedrockagent_agent_alias.digest.agent_alias_id
  description = "The alias the worker invokes. Invoking an agent id without an alias reaches the draft version, which is not a deployable target."
}

output "digest_worker_function_name" {
  value = aws_lambda_function.digest_worker.function_name
}

output "digest_tools_function_name" {
  value = aws_lambda_function.digest_tools.function_name
}

output "suggester_agent_id" {
  value = aws_bedrockagent_agent.suggester.agent_id
}

output "suggester_agent_alias_id" {
  value = aws_bedrockagent_agent_alias.suggester.agent_alias_id
}

output "suggester_worker_function_name" {
  value = aws_lambda_function.suggester_worker.function_name
}
