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
  # `aws_cognito_user_pool_domain.this.domain` is only the domain PREFIX -- the real
  # Hosted UI host is that prefix plus `.auth.<region>.amazoncognito.com` (a Cognito-
  # managed domain, not a custom one, confirmed via `aws cognito-idp describe-user-
  # pool-domain`). Every consumer (`sign-in.component.ts`, `auth.service.ts`'s
  # `signOut`) does a bare `https://${domain}/...`, so this output must be the full,
  # directly-usable host, not the prefix. Found live during spec 004's T032: every
  # real sign-in attempt since spec 001 redirected to an unresolvable host, never
  # caught because no live-verification session had completed a real browser sign-in
  # before that one.
  value = "${aws_cognito_user_pool_domain.this.domain}.auth.${data.aws_region.current.name}.amazoncognito.com"
}

output "group_names" {
  description = "The three role groups. The first administrator is added to one of these by hand (FR-039)."
  value       = [for g in aws_cognito_user_group.roles : g.name]
}
