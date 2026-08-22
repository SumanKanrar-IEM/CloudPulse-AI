output "user_pool_id" {
  value = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "Consumed by the API Gateway JWT authorizer (FR-034)."
  value       = aws_cognito_user_pool.this.arn
}

output "user_pool_endpoint" {
  description = "JWT issuer. The authorizer validates tokens against this."
  value       = "https://${aws_cognito_user_pool.this.endpoint}"
}

output "client_id" {
  value = aws_cognito_user_pool_client.web.id
}

output "hosted_ui_domain" {
  value = aws_cognito_user_pool_domain.this.domain
}

output "group_names" {
  description = "The three role groups. The first administrator is added to one of these by hand (FR-039)."
  value       = [for g in aws_cognito_user_group.roles : g.name]
}
