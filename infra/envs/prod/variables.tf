variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "vpc_cidr" {
  type = string
}

variable "azs" {
  type = list(string)
}

# --- Retention. Values fixed by the clarification session; see FR-005b, FR-046a,
# --- FR-029a and SC-014. Declared here so SC-014 is verifiable by inspecting the
# --- environment rather than by reading code.
variable "log_retention_days" {
  type        = number
  description = "CloudWatch log retention (FR-046a). 30 days."
  default     = 30

  validation {
    condition     = var.log_retention_days == 30
    error_message = "FR-046a fixes structured-log retention at 30 days."
  }
}

variable "backup_retention_days" {
  type        = number
  description = "Aurora automated backup retention (FR-005b). 7 days."
  default     = 7
}

# --- Identity. FR-039a: the group-to-role mapping is DATA in the versioned
# --- definitions, so a freshly provisioned environment is governed identically to
# --- an existing one. FR-031a: the directory is the sole authority for roles.
variable "role_group_map" {
  type        = map(string)
  description = "Cognito group name -> platform role (FR-032, FR-039a)."
  default = {
    "cloudpulse-admins"    = "admin"
    "cloudpulse-operators" = "operator"
    "cloudpulse-viewers"   = "viewer"
  }

  validation {
    condition = length(var.role_group_map) == 3 && alltrue([
      for r in values(var.role_group_map) : contains(["admin", "operator", "viewer"], r)
    ])
    error_message = "FR-032 defines exactly three roles: admin, operator, viewer."
  }
}

# --- Aurora Serverless v2 sizing. Demo-scale per plan.md: ~10 concurrent users.
variable "min_acu" {
  type        = number
  description = "Minimum Aurora Capacity Units. 0.5 is the floor while staying warm."
  default     = 0.5
}

variable "max_acu" {
  type    = number
  default = 2
}

variable "enable_rds_proxy" {
  type        = bool
  description = "research.md R-003. false takes the documented no-proxy fallback at demo scale."
  default     = true
}

# --- Lambda package, built by CI and passed in. Not committed.
variable "package_path" {
  type        = string
  description = "Path to the backend deployment zip."
  default     = "../../../backend/dist/lambda.zip"
}

variable "package_hash" {
  type        = string
  description = "base64 sha256 of the package, so a code change redeploys."
  default     = ""
}

variable "git_sha" {
  type    = string
  default = "unknown"
}

# --- Observability (S7). P2: droppable without affecting any P1 criterion.
variable "enable_observability" {
  type        = bool
  description = "P2 stretch (FR-049..FR-053). false leaves the P1 demo path intact."
  default     = false
}

variable "alert_email" {
  type        = string
  description = "Where alarms are delivered (FR-051). AWS requires the recipient to confirm."
  default     = ""
}

variable "api_error_threshold" {
  type        = number
  description = "5xx count over 5 minutes that trips the alarm (FR-050, decided at T116)."
  default     = 5
}

variable "dlq_names" {
  type    = list(string)
  default = []
}
