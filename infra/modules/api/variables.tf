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

variable "cognito_user_pool_id" {
  type    = string
  default = ""
}

variable "cognito_client_id" {
  type    = string
  default = ""
}

variable "log_retention_days" {
  type        = number
  description = "FR-046a: 30 days. Passed in so every module agrees (T044)."
}

variable "allowed_origins" {
  type        = list(string)
  description = "CORS origins. The CloudFront distribution only -- never '*'."
}

variable "package_path" {
  type        = string
  description = "Path to the deployment zip, built by CI."
}

variable "package_hash" {
  type        = string
  description = "base64 sha256 of the package, so a code change redeploys."
}

variable "git_sha" {
  type    = string
  default = "unknown"
}

variable "cognito_user_pool_endpoint" {
  type        = string
  description = "JWT issuer URL. Empty leaves routes unauthenticated (bootstrap only)."
  default     = ""
}

variable "cognito_user_pool_arn" {
  type    = string
  default = ""
}

variable "group_role_map_encoded" {
  type        = string
  description = "group:role pairs, comma separated. Mirrors role_group_map (FR-039a)."
  default     = ""
}

variable "enable_cognito_auth" {
  type        = bool
  description = <<-DESC
    Whether to attach the JWT authorizer (FR-034).

    A literal boolean rather than `cognito_user_pool_endpoint != ""` because Terraform
    cannot evaluate `count` against a value that is unknown until apply, and the pool
    endpoint comes from a sibling module. Set false only for a bootstrap apply where
    the pool does not exist yet -- the application still enforces FR-032a independently
    (research.md R-004, layer 2), but every route would be publicly reachable, so it
    must not stay false.
  DESC
  default     = true
}
