variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "vpc_id" { type = string }
variable "private_subnet_ids" { type = list(string) }

variable "db_host" { type = string }
variable "db_name" { type = string }
variable "db_user" { type = string }

variable "db_secret_arn" {
  type        = string
  description = "Secrets Manager ARN. A reference, never a value (Principle III, FR-007)."

  validation {
    condition     = startswith(var.db_secret_arn, "arn:aws:secretsmanager:")
    error_message = "Must be a Secrets Manager ARN, not a credential value (Principle III)."
  }
}

variable "log_retention_days" {
  type        = number
  description = "FR-046a: 30 days. Passed in so every module agrees (T044, spec 1)."
}

variable "package_path" {
  type        = string
  description = "Path to the deployment zip, built by CI -- the same package api/scan/governance's Lambdas use."
}

variable "package_hash" {
  type        = string
  description = "base64 sha256 of the package, so a code change redeploys."
}

variable "cost_ingestion_schedule_expression" {
  type        = string
  description = "FR-001: the daily spend-ingestion schedule. One hour after scan's own default (research.md), not because ingestion depends on that day's scan completing -- it doesn't -- but so a fresh SDA registration from earlier the same run window is available for attribution."
  default     = "cron(0 7 * * ? *)"
}
