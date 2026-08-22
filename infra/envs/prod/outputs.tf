output "frontend_url" {
  description = "Where the platform is reachable (FR-047)."
  value       = module.frontend.url
}

output "frontend_bucket" {
  description = "S3 origin bucket name, for the deploy workflow's `aws s3 sync` (distinct from frontend_url, which is the CloudFront domain)."
  value       = module.frontend.bucket_name
}

output "cloudfront_distribution_id" {
  description = "For invalidating the CDN cache after a frontend publish."
  value       = module.frontend.distribution_id
}

output "database_endpoint" {
  description = "What the application connects to (proxy when enabled)."
  value       = module.database.connection_endpoint
}

output "database_secret_arn" {
  description = "Secrets Manager ARN. A reference, never a value (Principle III)."
  value       = module.database.master_user_secret_arn
}

output "snapshot_bucket" {
  value = module.storage.bucket_name
}

output "vpc_id" {
  value = module.network.vpc_id
}

output "private_subnet_ids" {
  value = module.network.private_subnet_ids
}

output "api_endpoint" {
  description = "Base URL of the HTTP API (FR-047)."
  value       = module.api.api_endpoint
}

output "cognito_user_pool_id" {
  value = module.identity.user_pool_id
}

output "cognito_group_names" {
  description = "Add the first administrator to the admin group by hand (FR-039)."
  value       = module.identity.group_names
}

output "migrate_function_name" {
  description = "Invoked by the deploy workflows before the API alias shifts (FR-016)."
  value       = module.api.migrate_function_name
}

output "pre_token_function_arn" {
  description = "Wire into the Cognito pre-token trigger on the second apply (R-004)."
  value       = module.api.pre_token_function_arn
}

output "alerts_topic_arn" {
  description = "P2. Null when observability is disabled."
  value       = try(module.observability[0].alerts_topic_arn, null)
}

output "dashboard_name" {
  description = "P2. Null when observability is disabled."
  value       = try(module.observability[0].dashboard_name, null)
}
