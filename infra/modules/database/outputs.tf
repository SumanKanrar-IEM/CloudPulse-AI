output "cluster_endpoint" {
  value = aws_rds_cluster.this.endpoint
}

output "connection_endpoint" {
  description = "What the application connects to: the proxy when enabled, otherwise the cluster."
  value       = var.enable_rds_proxy ? aws_db_proxy.this[0].endpoint : aws_rds_cluster.this.endpoint
}

output "database_name" {
  value = aws_rds_cluster.this.database_name
}

output "master_user_secret_arn" {
  description = "Secrets Manager ARN of the RDS-managed master credential. A reference, never a value (Principle III)."
  value       = aws_rds_cluster.this.master_user_secret[0].secret_arn
}

output "security_group_id" {
  value = aws_security_group.cluster.id
}
