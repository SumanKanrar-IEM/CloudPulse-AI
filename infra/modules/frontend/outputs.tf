output "bucket_name" {
  value = aws_s3_bucket.origin.id
}

output "distribution_id" {
  value = aws_cloudfront_distribution.this.id
}

output "url" {
  description = "Where the platform is reachable (FR-047)."
  value       = "https://${aws_cloudfront_distribution.this.domain_name}"
}
