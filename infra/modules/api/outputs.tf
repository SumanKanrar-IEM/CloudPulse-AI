output "api_endpoint" {
  description = "Base URL of the HTTP API (FR-047)."
  value       = aws_apigatewayv2_api.this.api_endpoint
}

output "api_id" {
  value = aws_apigatewayv2_api.this.id
}

output "migrate_function_name" {
  description = "Invoked by the deploy workflows before the API alias shifts (FR-016)."
  value       = aws_lambda_function.migrate.function_name
}

output "lambda_role_arn" {
  value = aws_iam_role.lambda.arn
}

output "lambda_security_group_id" {
  value = aws_security_group.lambda.id
}

output "pre_token_function_arn" {
  description = "Wired into the Cognito pool's pre-token-generation trigger (R-004)."
  value       = aws_lambda_function.pre_token.arn
}
