variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "vpc_id" { type = string }
variable "vpc_cidr" { type = string }
variable "private_subnet_ids" { type = list(string) }

variable "engine_version" {
  type    = string
  default = "16.4"
}

# Demo-scale (plan.md Technical Context): ~10 concurrent users. 0.5 ACU is the floor
# Aurora Serverless v2 allows while remaining warm.
variable "min_acu" {
  type    = number
  default = 0.5
}

variable "max_acu" {
  type    = number
  default = 2
}

variable "backup_retention_days" {
  type        = number
  description = "FR-005b: 7 days."
  default     = 7
}

variable "log_retention_days" {
  type        = number
  description = "FR-046a: 30 days. Passed in from the environment so every module agrees."
}

variable "enable_rds_proxy" {
  type        = bool
  description = "R-003. Set false to take the documented no-proxy fallback at demo scale."
  default     = true
}

variable "snapshot_suffix" {
  type        = string
  description = "Suffix for the prod final snapshot identifier. Must be unique per destroy."
  default     = "manual"
}
