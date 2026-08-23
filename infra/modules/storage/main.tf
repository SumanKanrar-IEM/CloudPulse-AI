# Raw scan snapshots (FR-016 persistence, consumed by spec 2).
#
# This spec provisions the bucket and its guardrails only. The lifecycle policy — how
# long snapshots live — is spec 2's to define, because it owns the scan lifecycle.
# FR-029a's "no expiry mechanism" rule applies to audit events, not to snapshots.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

resource "aws_s3_bucket" "snapshots" {
  bucket = "cloudpulse-${var.environment}-snapshots-${var.account_id}"
}

# Snapshots are immutable evidence: a finding traces back to the account state that
# produced it. Versioning means an overwrite cannot silently rewrite history.
resource "aws_s3_bucket_versioning" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "snapshots" {
  bucket                  = aws_s3_bucket.snapshots.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# spec 002, research.md R-207: raw snapshots are operational data for diffing, not an
# audit trail -- 30-day-class retention (matching FR-046a's precedent for structured
# logs), not indefinite retention like audit_event.
resource "aws_s3_bucket_lifecycle_configuration" "snapshots" {
  bucket = aws_s3_bucket.snapshots.id
  rule {
    id     = "expire-raw-snapshots"
    status = "Enabled"
    filter {}
    expiration {
      days = 30
    }
    noncurrent_version_expiration {
      noncurrent_days = 30
    }
  }
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "account_id" { type = string }

output "bucket_name" {
  value = aws_s3_bucket.snapshots.id
}

output "bucket_arn" {
  value = aws_s3_bucket.snapshots.arn
}
