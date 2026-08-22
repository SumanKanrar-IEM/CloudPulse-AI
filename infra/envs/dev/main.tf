# dev environment.
#
# FR-002: dev and prod are provisioned from ONE shared module set, with only
# per-environment values differing. There is no separate, divergent definition set —
# if a change is needed here that is not a variable, it belongs in the module.

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "cloudpulse-ai"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # FR-046a / SC-014, task T044. Every module that creates a log group consumes this
  # single value, so a module added in a later phase inherits 30-day retention rather
  # than needing a retroactive sweep. Hardcoding it per module is the failure mode
  # this exists to prevent.
  log_retention_days = var.log_retention_days
}

module "network" {
  source      = "../../modules/network"
  environment = var.environment
  vpc_cidr    = var.vpc_cidr
  azs         = var.azs
}

module "database" {
  source                = "../../modules/database"
  environment           = var.environment
  vpc_id                = module.network.vpc_id
  vpc_cidr              = module.network.vpc_cidr
  private_subnet_ids    = module.network.private_subnet_ids
  backup_retention_days = var.backup_retention_days
  log_retention_days    = local.log_retention_days
  min_acu               = var.min_acu
  max_acu               = var.max_acu
  enable_rds_proxy      = var.enable_rds_proxy
}

module "storage" {
  source      = "../../modules/storage"
  environment = var.environment
  account_id  = local.account_id
}

module "frontend" {
  source      = "../../modules/frontend"
  environment = var.environment
  account_id  = local.account_id
}

module "identity" {
  source      = "../../modules/identity"
  environment = var.environment
  account_id  = local.account_id
  # FR-039a: the group-to-role mapping is data in the versioned definitions.
  role_group_map = var.role_group_map
  callback_urls  = ["${module.frontend.url}/auth/callback"]
  logout_urls    = [module.frontend.url]
  # Wired after the api module exists; a two-pass apply on first provision.
  pre_token_lambda_arn = ""
}

module "api" {
  source             = "../../modules/api"
  environment        = var.environment
  vpc_id             = module.network.vpc_id
  private_subnet_ids = module.network.private_subnet_ids

  db_host       = module.database.connection_endpoint
  db_name       = module.database.database_name
  db_user       = "cloudpulse_admin"
  db_secret_arn = module.database.master_user_secret_arn

  cognito_user_pool_id       = module.identity.user_pool_id
  cognito_user_pool_arn      = module.identity.user_pool_arn
  cognito_user_pool_endpoint = module.identity.user_pool_endpoint
  cognito_client_id          = module.identity.client_id

  # Mirrors role_group_map so the Lambda and Terraform cannot drift (FR-039a).
  group_role_map_encoded = join(",", [for g, r in var.role_group_map : "${g}:${r}"])

  log_retention_days = local.log_retention_days
  allowed_origins    = [module.frontend.url]
  package_path       = var.package_path
  package_hash       = var.package_hash
  git_sha            = var.git_sha
}

# --- P2. Constitution Principle VIII: nothing here may block or destabilise a P1
# --- path. Set enable_observability = false and every P1 success criterion still holds.
module "observability" {
  count  = var.enable_observability ? 1 : 0
  source = "../../modules/observability"

  environment         = var.environment
  aws_region          = var.aws_region
  api_id              = module.api.api_id
  alert_email         = var.alert_email
  api_error_threshold = var.api_error_threshold
  # Populated as specs 002/003/005 add workers with dead-letter queues.
  dlq_names = var.dlq_names
}
