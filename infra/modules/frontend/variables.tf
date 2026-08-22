variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "account_id" {
  type        = string
  description = "Used to make the bucket name globally unique."
}
