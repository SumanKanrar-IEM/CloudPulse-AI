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
  description = "FR-046a: 30 days. Passed in so every module agrees."
}

variable "package_path" {
  type        = string
  description = "Path to the deployment zip built by CI -- the same package every other worker uses."
}

variable "package_hash" {
  type        = string
  description = "base64 sha256 of the package, so a code change redeploys."
}

variable "agent_package_path" {
  type        = string
  description = "Path to the AgentCore artefact zip built by CI: agents/runtime/main.py at the root, definitions/ prompts/ action-groups/ beside it, boto3 vendored, no bytecode (R-613a, R-613b). Uploaded to this module's artefact bucket."
}

variable "agent_package_hash" {
  type        = string
  description = "hex md5 of the agent package (S3's etag form), so a code change re-uploads and the runtime re-pins."
}

variable "digest_schedule_expression" {
  type        = string
  description = "FR-008: one daily digest. After the cost module's 07:00 ingestion and 08:00 notification passes, so the day's spend is ingested before the digest reports on it."
  default     = "cron(0 9 * * ? *)"
}

variable "advisor_schedule_expression" {
  type        = string
  description = "FR-015: one daily advisor pass, after the 06:00 scan so it reads today's inventory. Deterministic and cheap -- no model call."
  default     = "cron(0 8 * * ? *)"
}

variable "metrics_schedule_expression" {
  type        = string
  description = "FR-019: one daily metrics collection for the previous UTC day, after the 06:00 scan. Cost tracks inventory size (R-606) -- the lever is METRIC_QUERIES, not this schedule."
  default     = "cron(30 7 * * ? *)"
}

variable "suggester_schedule_expression" {
  type        = string
  description = "FR-011: one daily suggester pass, after the digest's. Both read the same findings, and the digest reports on findings rather than on their suggestions, so there is nothing to gain from running the suggester first."
  default     = "cron(0 10 * * ? *)"
}

variable "platform_api_base_url" {
  type        = string
  description = "R-602: the API Gateway base the action group reads through. Empty leaves the action group deployed but refusing to call anything, rather than silently reaching a wrong host."
  default     = ""
}

variable "cognito_token_endpoint" {
  type        = string
  description = "The Cognito domain's /oauth2/token URL. The action group exchanges its client credentials here for the read-only agent principal (FR-056)."
  default     = ""
}

variable "agent_client_id" {
  type        = string
  description = "The agent's Cognito machine app-client id. Not a secret; the secret is agent_client_secret_arn."
  default     = ""
}

variable "agent_client_secret_arn" {
  type        = string
  description = "Secrets Manager ARN holding the agent app client's secret as {\"client_secret\": \"...\"}. A reference, never a value (Principle III)."
  default     = ""

  validation {
    condition     = var.agent_client_secret_arn == "" || startswith(var.agent_client_secret_arn, "arn:aws:secretsmanager:")
    error_message = "Must be a Secrets Manager ARN, not a credential value (Principle III)."
  }
}

variable "agent_cost_cap_units" {
  type        = string
  description = "FR-004: the per-run token cap, input plus output. research.md R-612 -- read from the environment at point of use, not from the shared Settings model."
  default     = "200000"
}

variable "digest_spend_notable_percent" {
  type        = string
  description = "FR-008b: a day-over-day spend move at least this large, as a percentage, is notable. Either this or the absolute bar triggers, whichever comes first."
  default     = "20"
}

variable "digest_spend_notable_usd" {
  type        = string
  description = "FR-008b: a day-over-day spend move at least this large in USD is notable, whatever the percentage. This is the bar that catches a large project moving a meaningful amount that reads as a small fraction."
  default     = "50"
}

variable "digest_compliance_notable_points" {
  type        = string
  description = "FR-008b: a compliance score move of at least this many points, in either direction, is notable."
  default     = "5"
}
