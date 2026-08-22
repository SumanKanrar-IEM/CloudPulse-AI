# Aurora Serverless v2 PostgreSQL — the governance record (FR-024).
#
# Principle III (NON-NEGOTIABLE): the master password is managed by RDS itself via
# `manage_master_user_password`. AWS generates it, stores it in Secrets Manager, and
# rotates it. It never appears in Terraform state, in a variable, in a tfvars file, or
# in this repository. There is deliberately no `master_password` argument anywhere.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

locals {
  name    = "cloudpulse-${var.environment}"
  is_prod = var.environment == "prod"
}

resource "aws_db_subnet_group" "this" {
  name       = local.name
  subnet_ids = var.private_subnet_ids
}

resource "aws_security_group" "cluster" {
  name        = "${local.name}-aurora"
  description = "Aurora cluster — reachable only from within the VPC"
  vpc_id      = var.vpc_id

  ingress {
    description = "PostgreSQL from inside the VPC"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }

  egress {
    description = "Cluster-initiated egress (AWS APIs via VPC endpoints)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_rds_cluster" "this" {
  cluster_identifier = local.name
  engine             = "aurora-postgresql"
  engine_version     = var.engine_version
  database_name      = "cloudpulse"
  master_username    = "cloudpulse_admin"

  # Principle III: AWS creates, stores and rotates the password. No plaintext, ever.
  manage_master_user_password = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [aws_security_group.cluster.id]

  storage_encrypted = true

  # FR-005b / SC-014: 7-day backup retention. Fixed by the clarification session.
  backup_retention_period = var.backup_retention_days
  preferred_backup_window = "03:00-04:00"

  # FR-005a / R-010, layer 1 of three.
  #
  # Layer 2 -- `lifecycle { prevent_destroy = true }` -- is NOT implemented here, and
  # cannot be: Terraform requires prevent_destroy to be a literal, so it cannot be
  # made conditional on var.environment. In a module shared by dev and prod (FR-002
  # requires one shared module set), enabling it would also block routine dev
  # teardown, which FR-005 explicitly permits.
  #
  # The spec assumed a capability Terraform does not have. Layers 1 and 3 both hold:
  #   layer 1  deletion_protection below -- prod only, refuses at the cluster
  #   layer 3  ops/teardown.sh guard     -- refuses BEFORE anything is touched,
  #                                          which is what the "teardown aimed at
  #                                          prod" edge case actually requires
  # Layer 2 would have been the weakest of the three anyway: it fails partway through
  # a plan rather than up front.
  deletion_protection = local.is_prod

  # A final snapshot on prod is the difference between a recoverable mistake and an
  # unrecoverable one. Registered accounts, tag rules, the SDA registry and the
  # append-only audit trail are human-entered and cannot be rebuilt by re-scanning.
  skip_final_snapshot       = !local.is_prod
  final_snapshot_identifier = local.is_prod ? "${local.name}-final-${var.snapshot_suffix}" : null

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  enabled_cloudwatch_logs_exports = ["postgresql"]
}

resource "aws_rds_cluster_instance" "this" {
  identifier          = "${local.name}-1"
  cluster_identifier  = aws_rds_cluster.this.id
  instance_class      = "db.serverless"
  engine              = aws_rds_cluster.this.engine
  engine_version      = aws_rds_cluster.this.engine_version
  publicly_accessible = false
}

# --- RDS Proxy (research.md R-003) ---------------------------------------
#
# Lambda concurrency multiplies raw connections and Aurora Serverless v2 at a low
# minimum ACU has a modest connection ceiling. The proxy pools on the far side of the
# boundary; the API Lambda uses SQLAlchemy NullPool so a frozen execution context
# cannot strand a connection.
#
# R-003 records "no proxy at demo scale" as the documented fallback if its cost proves
# material. Set var.enable_rds_proxy = false to take it.

resource "aws_iam_role" "proxy" {
  count = var.enable_rds_proxy ? 1 : 0
  name  = "${local.name}-rds-proxy"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "rds.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "proxy_secret" {
  count = var.enable_rds_proxy ? 1 : 0
  name  = "read-master-secret"
  role  = aws_iam_role.proxy[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
      Resource = aws_rds_cluster.this.master_user_secret[0].secret_arn
    }]
  })
}

resource "aws_db_proxy" "this" {
  count                  = var.enable_rds_proxy ? 1 : 0
  name                   = local.name
  engine_family          = "POSTGRESQL"
  role_arn               = aws_iam_role.proxy[0].arn
  vpc_subnet_ids         = var.private_subnet_ids
  vpc_security_group_ids = [aws_security_group.cluster.id]
  require_tls            = true

  auth {
    auth_scheme = "SECRETS"
    iam_auth    = "DISABLED"
    secret_arn  = aws_rds_cluster.this.master_user_secret[0].secret_arn
  }
}

resource "aws_db_proxy_default_target_group" "this" {
  count         = var.enable_rds_proxy ? 1 : 0
  db_proxy_name = aws_db_proxy.this[0].name

  connection_pool_config {
    max_connections_percent      = 90
    connection_borrow_timeout    = 120
    max_idle_connections_percent = 50
  }
}

resource "aws_db_proxy_target" "this" {
  count                 = var.enable_rds_proxy ? 1 : 0
  db_cluster_identifier = aws_rds_cluster.this.id
  db_proxy_name         = aws_db_proxy.this[0].name
  target_group_name     = aws_db_proxy_default_target_group.this[0].name
}

# FR-046a / SC-014: 30-day log retention, consuming the shared value rather than
# hardcoding it — so a module added in a later phase inherits it (T044).
resource "aws_cloudwatch_log_group" "postgresql" {
  name              = "/aws/rds/cluster/${local.name}/postgresql"
  retention_in_days = var.log_retention_days
}
