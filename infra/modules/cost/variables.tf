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

variable "frontend_url" {
  type        = string
  description = "FR-005: the base the notification worker builds its /findings/{id} deep link on. The same CloudFront domain the API already receives as its single allowed CORS origin."
  default     = ""
}

variable "notification_sender_email" {
  type        = string
  description = "FR-014: the fixed, per-environment SES sending identity. A verified identity in the platform's own account, never a per-tenant address. Empty leaves the worker deployed but refusing to run (T015), rather than silently sending from an unverified address."
  default     = ""
}

variable "notification_schedule_expression" {
  type        = string
  description = "research.md R-501: one daily pass answering 'what is due today' for every cadence point. After cost ingestion, so a budget_overrun finding opened by that run is notifiable the same day."
  default     = "cron(0 8 * * ? *)"
}

variable "iam_hygiene_schedule_expression" {
  type        = string
  description = "research.md R-510: weekly, not daily. IAM last-used data changes slowly and the unused window is 90 days, so a daily run would cost seven times the invocations to surface a flag at most a day sooner."
  default     = "cron(0 9 ? * SUN *)"
}
