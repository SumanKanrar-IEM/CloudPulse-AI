# Bootstrap — the ONE manual step FR-001a permits.
#
# Applied by hand, once per AWS account, by someone with account-level credentials.
# Everything else in this repository is applied by GitHub Actions through OIDC.
#
# Why this cannot be automated away (research.md R-001):
#   - a remote state backend cannot store its own creation, and
#   - an OIDC trust relationship cannot be created by a workflow that has no role
#     to assume yet.
#
# FR-001a bounds it: versioned definitions, applied once, creating NO long-lived
# credential, counted in the FR-006 runbook and the SC-001 60-minute budget.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    # Used by oidc.tf to read GitHub's OIDC signing certificate for the thumbprint.
    # Terraform would auto-install it, but an undeclared provider is an implicit
    # dependency that a version bump can break silently.
    tls = {
      source  = "hashicorp/tls"
      version = "~> 4.0"
    }
  }

  # Deliberately no backend block: this root module creates the backend.
  # Its own state is local and is not committed (see .gitignore).
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cloudpulse-ai"
      Environment = var.environment
      ManagedBy   = "terraform"
      Component   = "bootstrap"
    }
  }
}

variable "aws_region" {
  type        = string
  description = "Region for the state backend and OIDC provider."
  default     = "us-east-1"
}

variable "environment" {
  type        = string
  description = "dev or prod (FR-002)."

  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "github_repository" {
  type        = string
  description = "owner/repo that may assume the deploy role."
  default     = "SumanKanrar-IEM/CloudPulse-AI"
}

# GitHub now embeds the numeric owner and repository IDs in the OIDC `sub` claim by
# default (confirmed via `gh api repos/OWNER/REPO/actions/oidc/customization/sub`,
# which returns `use_default: true` alongside a `sub_claim_prefix` that already
# contains "@<owner_id>/<repo>@<repo_id>"). This is separate from the opt-in
# "immutable subject" toggle -- it is GitHub's current default, and a trust policy
# written against the old plain `repo:OWNER/REPO:...` format is silently rejected
# with a generic "Not authorized to perform sts:AssumeRoleWithWebIdentity", which
# gives no hint that the claim format is the problem.
#
# Both forms are supported below so this keeps working whichever way GitHub's
# default moves next. Find the current values with:
#   gh api user -q .id
#   gh api repos/<owner>/<repo> -q .id
variable "github_owner_id" {
  type        = string
  description = "Numeric GitHub user/org id. Empty skips the immutable-ID trust condition."
  default     = "25535680"
}

variable "github_repo_id" {
  type        = string
  description = "Numeric GitHub repository id. Empty skips the immutable-ID trust condition."
  default     = "1338836612"
}

locals {
  state_bucket = "cloudpulse-tfstate-${var.environment}-${data.aws_caller_identity.current.account_id}"
  lock_table   = "cloudpulse-tflock-${var.environment}"
}

data "aws_caller_identity" "current" {}

# --- Terraform state -------------------------------------------------------

resource "aws_s3_bucket" "state" {
  bucket = local.state_bucket

  # prevent_destroy intentionally OFF: the maintainer needs to be able to tear the
  # whole account down cleanly at the end of the build.
  #
  # The foundation is still protected where it matters — the ProtectBootstrapFoundation
  # DENY in deploy_policy.tf blocks the GitHub deploy role from deleting this bucket,
  # so no pipeline run can destroy it. Only a deliberate local admin action can.
  #
  # Consequence to be aware of: destroying this bucket destroys the Terraform state for
  # every environment. Re-bootstrapping is possible, but any resources already created
  # become orphaned and must be imported or deleted by hand.
}

resource "aws_s3_bucket_versioning" "state" {
  bucket = aws_s3_bucket.state.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "state" {
  bucket = aws_s3_bucket.state.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "state" {
  bucket                  = aws_s3_bucket.state.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "lock" {
  name         = local.lock_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "LockID"

  attribute {
    name = "LockID"
    type = "S"
  }

}

output "state_bucket" {
  value       = aws_s3_bucket.state.id
  description = "Set this as `bucket` in infra/envs/<env>/backend.tf."
}

output "lock_table" {
  value       = aws_dynamodb_table.lock.name
  description = "Set this as `dynamodb_table` in infra/envs/<env>/backend.tf."
}
