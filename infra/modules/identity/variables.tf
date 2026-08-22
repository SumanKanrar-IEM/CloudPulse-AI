variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "account_id" {
  type        = string
  description = "Used to make the Cognito domain globally unique."
}

variable "role_group_map" {
  type        = map(string)
  description = "Cognito group name -> platform role (FR-032, FR-039a)."

  validation {
    condition = length(var.role_group_map) == 3 && alltrue([
      for r in values(var.role_group_map) : contains(["admin", "operator", "viewer"], r)
    ])
    error_message = "FR-032 defines exactly three roles: admin, operator, viewer."
  }

  validation {
    # FR-032a refuses a multi-group identity, so two groups mapping to the same role
    # would be an ambiguity the platform cannot resolve.
    condition     = length(distinct(values(var.role_group_map))) == 3
    error_message = "Each group must map to a distinct role."
  }
}

variable "pre_token_lambda_arn" {
  type        = string
  description = "research.md R-004 layer 1. Empty disables the trigger; the API still enforces FR-032a."
  default     = ""
}

variable "callback_urls" {
  type    = list(string)
  default = []
}

variable "logout_urls" {
  type    = list(string)
  default = []
}
