
output "oidc_provider_arn" {
  description = "The resolved ARN, whether created by this apply or looked up (create_oidc_provider)."
  value       = local.oidc_provider_arn
}
