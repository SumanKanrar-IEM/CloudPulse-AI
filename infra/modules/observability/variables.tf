variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "aws_region" { type = string }

variable "api_id" {
  type        = string
  description = "API Gateway id, for the 5xx metric dimension."
}

variable "alert_email" {
  type        = string
  description = "Where alerts are delivered (FR-051). Empty skips the subscription."
  default     = ""
}

# --- Thresholds. FR-050 left these as "agreed threshold"; T116 decides them.
# --- Reasoning is in main.tf next to each alarm, not here, so it stays with the code
# --- that uses it.
variable "api_error_threshold" {
  type        = number
  description = "5xx count over 5 minutes that trips the alarm. See T116 reasoning."
  default     = 5

  validation {
    condition     = var.api_error_threshold >= 1
    error_message = "A threshold of 0 would fire on every evaluation period."
  }
}

variable "dlq_names" {
  type        = list(string)
  description = "Dead-letter queues to watch. Populated as specs 002/003/005 add workers."
  default     = []
}
