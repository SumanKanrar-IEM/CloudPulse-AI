# Scan orchestration: Step Functions state machine, EventBridge Scheduler rule,
# scan-worker Lambda, IAM roles scoped to sts:AssumeRole on cross-account scanner
# roles only (spec 002, T042). Placeholder -- filled in Phase 6.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}
