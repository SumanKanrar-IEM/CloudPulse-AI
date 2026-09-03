# Cost, utilization, and notification workers (spec 005). Three Lambdas land in this
# module across three phases (T009, T016, T047) -- this file starts with just
# cost-ingestion-worker; notification-worker and iam-hygiene-worker are added by their
# own later tasks, matching governance/scan's own precedent of one module built up
# across a spec's phases rather than scaffolded whole up front.

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
  name = "cloudpulse-${var.environment}"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- cost-ingestion-worker Lambda (FR-001, research.md R-503) -----------------------

resource "aws_security_group" "cost_ingestion_worker" {
  name        = "${local.name}-cost-ingestion-worker"
  description = "Cost-ingestion worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora, cross-account scanner roles, and AWS APIs (Cost Explorer)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "cost_ingestion_worker_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cost_ingestion_worker" {
  name               = "${local.name}-cost-ingestion-worker"
  assume_role_policy = data.aws_iam_policy_document.cost_ingestion_worker_assume.json
}

resource "aws_iam_role_policy_attachment" "cost_ingestion_worker_vpc" {
  role       = aws_iam_role.cost_ingestion_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "cost_ingestion_worker" {
  name              = "/aws/lambda/${local.name}-cost-ingestion-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "cost_ingestion_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # research.md R-503: the same ExternalId secret read spec 002/003's own workers
  # already grant themselves, scoped identically to connectors/aws.py's own
  # secret-naming convention -- never a scanned account's own secrets.
  statement {
    sid       = "ReadExternalIdSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:cloudpulse/external-id/*"]
  }

  # research.md R-503/R-206: assume the target account's scanner role, once per
  # account unit of work -- the identical scope every existing worker already
  # carries. Not a new role.
  statement {
    sid       = "AssumeScannerRole"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/cloudpulse-scanner"]
  }

  # FR-001, research.md R-503: the one AWS read this worker performs (directly for
  # same-account/local mode; cross-account mode's call flows through the assumed
  # scanner role above instead). Cost Explorer has no resource-level ARN scoping.
  statement {
    sid       = "GetCostAndUsage"
    effect    = "Allow"
    actions   = ["ce:GetCostAndUsage"]
    resources = ["*"]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.cost_ingestion_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "cost_ingestion_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.cost_ingestion_worker.id
  policy = data.aws_iam_policy_document.cost_ingestion_worker_runtime.json
}

resource "aws_lambda_function" "cost_ingestion_worker" {
  function_name = "${local.name}-cost-ingestion-worker"
  role          = aws_iam_role.cost_ingestion_worker.arn
  handler       = "handlers.cost_ingestion_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"] # research.md R-510: ~20% cheaper than x86 per GB-second.
  timeout       = 120       # one ce:GetCostAndUsage call per registered account, sequential.
  memory_size   = 512       # DB writes + one AWS call per account -- no CPU-bound work.

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.cost_ingestion_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
      POWERTOOLS_SERVICE_NAME  = "cloudpulse-cost-ingestion-worker"
      POWERTOOLS_LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.cost_ingestion_worker]
}

# --- notification-worker Lambda (T016; FR-004, FR-005, FR-014, research.md R-504) ---
#
# Deliberately NO PrivateLink endpoint and no NAT gateway, per research.md R-504's
# declined funding decision: SES *is* reachable from a VPC via the
# com.amazonaws.<region>.email interface endpoint, and that was verified, but the
# ~$14.40/month for two AZs was not funded. Everything below deploys cleanly and every
# notification rule is proven by the mocked tests; the ses:SendEmail call itself cannot
# reach AWS from inside the VPC until that gap is funded. Stated here rather than
# discovered at runtime.

resource "aws_security_group" "notification_worker" {
  name        = "${local.name}-notification-worker"
  description = "Notification worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora, and to SES once the R-504 interface endpoint is funded."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "notification_worker" {
  name = "${local.name}-notification-worker"
  # Same Lambda service trust policy the cost-ingestion worker uses -- one document,
  # not a second identical one.
  assume_role_policy = data.aws_iam_policy_document.cost_ingestion_worker_assume.json
}

resource "aws_iam_role_policy_attachment" "notification_worker_vpc" {
  role       = aws_iam_role.notification_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "notification_worker" {
  name              = "/aws/lambda/${local.name}-notification-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "notification_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # FR-014: sending is scoped to the one configured identity, not to every identity
  # the account happens to verify. An unset sender scopes to "*" only because an
  # empty-string ARN would be a malformed policy document and would fail the whole
  # apply -- the worker itself refuses to run without the value (T015).
  statement {
    sid     = "SendOwnerNotifications"
    effect  = "Allow"
    actions = ["ses:SendEmail"]
    resources = var.notification_sender_email == "" ? ["*"] : [
      "arn:aws:ses:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:identity/${var.notification_sender_email}"
    ]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.notification_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "notification_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.notification_worker.id
  policy = data.aws_iam_policy_document.notification_worker_runtime.json
}

resource "aws_lambda_function" "notification_worker" {
  function_name = "${local.name}-notification-worker"
  role          = aws_iam_role.notification_worker.arn
  handler       = "handlers.notification_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"] # research.md R-510: ~20% cheaper than x86 per GB-second.
  timeout       = 120       # one SES call per due finding, sequential.
  memory_size   = 512       # DB reads plus one small API call per finding.

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.notification_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT               = var.environment
      CLOUDPULSE_AWS_REGION                = data.aws_region.current.name
      CLOUDPULSE_DB_HOST                   = var.db_host
      CLOUDPULSE_DB_NAME                   = var.db_name
      CLOUDPULSE_DB_USER                   = var.db_user
      CLOUDPULSE_DB_SECRET_ARN             = var.db_secret_arn
      CLOUDPULSE_FRONTEND_URL              = var.frontend_url
      CLOUDPULSE_NOTIFICATION_SENDER_EMAIL = var.notification_sender_email
      POWERTOOLS_SERVICE_NAME              = "cloudpulse-notification-worker"
      POWERTOOLS_LOG_LEVEL                 = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.notification_worker]
}
