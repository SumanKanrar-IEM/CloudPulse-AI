# Governance pipeline: two SQS-driven Lambda workers, enqueued by spec 002's
# `finalize_scan` on every finalized scan (spec 003, T025, research.md R-303).
#
# Two queues, not one -- validation (SDA matching, rule evaluation, scoring; all
# in-memory/DB-only, fast, no AWS calls) and ownership attribution (network-bound,
# rate-limited CloudTrail sweep, genuinely slower) have different failure and
# retry profiles (research.md R-303's own rationale). Standard queues, not FIFO
# (research.md R-306): each message is independently processable, so there is no
# ordering guarantee to pay FIFO's throughput cap for.

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

# --- SQS: compliance-validation ------------------------------------------------

resource "aws_sqs_queue" "compliance_validation_dlq" {
  name                      = "${local.name}-compliance-validation-dlq"
  message_retention_seconds = 1209600 # 14 days -- max, so a failed message survives investigation time.
}

resource "aws_sqs_queue" "compliance_validation" {
  name                       = "${local.name}-compliance-validation"
  visibility_timeout_seconds = 60 # >= the worker's own timeout, so a slow invocation is never redelivered mid-flight.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.compliance_validation_dlq.arn
    maxReceiveCount     = 5
  })
}

# --- SQS: ownership-attribution -------------------------------------------------

resource "aws_sqs_queue" "ownership_attribution_dlq" {
  name                      = "${local.name}-ownership-attribution-dlq"
  message_retention_seconds = 1209600
}

resource "aws_sqs_queue" "ownership_attribution" {
  name                       = "${local.name}-ownership-attribution"
  visibility_timeout_seconds = 300 # >= the worker's own timeout (below) -- CloudTrail's sweep is the slower of the two.
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.ownership_attribution_dlq.arn
    maxReceiveCount     = 5
  })
}

# --- Compliance-validation worker Lambda ----------------------------------------

resource "aws_security_group" "compliance_validation_worker" {
  name        = "${local.name}-compliance-validation-worker"
  description = "Compliance-validation worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora only -- SDA matching/rule evaluation/scoring is DB-only, no AWS calls (R-303)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "compliance_validation_worker_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "compliance_validation_worker" {
  name               = "${local.name}-compliance-validation-worker"
  assume_role_policy = data.aws_iam_policy_document.compliance_validation_worker_assume.json
}

resource "aws_iam_role_policy_attachment" "compliance_validation_worker_vpc" {
  role       = aws_iam_role.compliance_validation_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "compliance_validation_worker" {
  name              = "/aws/lambda/${local.name}-compliance-validation-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "compliance_validation_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }
  statement {
    sid       = "ConsumeOwnQueue"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.compliance_validation.arn]
  }
  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.compliance_validation_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "compliance_validation_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.compliance_validation_worker.id
  policy = data.aws_iam_policy_document.compliance_validation_worker_runtime.json
}

resource "aws_lambda_function" "compliance_validation_worker" {
  function_name = "${local.name}-compliance-validation-worker"
  role          = aws_iam_role.compliance_validation_worker.arn
  handler       = "handlers.compliance_validation_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"] # research.md R-306: ~20% cheaper than x86 per GB-second; demo-scale invocation count makes this immaterial to total cost regardless.
  timeout       = 60
  memory_size   = 1024 # research.md R-306: matches spec 002's scan-worker sizing.

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.compliance_validation_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
      POWERTOOLS_SERVICE_NAME  = "cloudpulse-compliance-validation-worker"
      POWERTOOLS_LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.compliance_validation_worker]
}

resource "aws_lambda_event_source_mapping" "compliance_validation_worker" {
  event_source_arn = aws_sqs_queue.compliance_validation.arn
  function_name    = aws_lambda_function.compliance_validation_worker.arn
  batch_size       = 1 # One finalized scan per invocation -- keeps failure isolation per-scan, matching the DLQ's per-message redrive.
}

# --- Ownership-attribution worker Lambda -----------------------------------------

resource "aws_security_group" "ownership_attribution_worker" {
  name        = "${local.name}-ownership-attribution-worker"
  description = "Ownership-attribution worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora, cross-account scanner roles, and AWS APIs (CloudTrail LookupEvents)."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "ownership_attribution_worker_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "ownership_attribution_worker" {
  name               = "${local.name}-ownership-attribution-worker"
  assume_role_policy = data.aws_iam_policy_document.ownership_attribution_worker_assume.json
}

resource "aws_iam_role_policy_attachment" "ownership_attribution_worker_vpc" {
  role       = aws_iam_role.ownership_attribution_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "ownership_attribution_worker" {
  name              = "/aws/lambda/${local.name}-ownership-attribution-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "ownership_attribution_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # FR-003a/research.md R-206: the same ExternalId secret read spec 002's own
  # scan-worker grants itself, scoped identically to connectors/aws.py's own
  # secret-naming convention -- never a scanned account's own secrets.
  statement {
    sid       = "ReadExternalIdSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:cloudpulse/external-id/*"]
  }

  # research.md R-206/R-302: assume the target account's scanner role, once per
  # (account, region) unit of work -- the identical scope spec 002's scan-worker
  # already carries, extended with cloudtrail:LookupEvents on the role itself
  # (cross_account_template.yaml). This is the "not a new role" IAM extension
  # T025 calls for -- there is no separate governance-specific scanner role.
  statement {
    sid       = "AssumeScannerRole"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/cloudpulse-scanner"]
  }

  # FR-020, research.md R-302/R-306: the one AWS read this worker performs
  # directly (for same-account/local connection mode; cross-account mode's
  # CloudTrail access flows through the assumed scanner role above instead).
  # Free API call, no Trail/S3/CloudWatch Logs delivery required or created.
  statement {
    sid       = "LookupCloudTrailEvents"
    effect    = "Allow"
    actions   = ["cloudtrail:LookupEvents"]
    resources = ["*"] # LookupEvents has no resource-level ARN scoping (AWS-side).
  }

  statement {
    sid       = "ConsumeOwnQueue"
    effect    = "Allow"
    actions   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
    resources = [aws_sqs_queue.ownership_attribution.arn]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.ownership_attribution_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "ownership_attribution_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.ownership_attribution_worker.id
  policy = data.aws_iam_policy_document.ownership_attribution_worker_runtime.json
}

resource "aws_lambda_function" "ownership_attribution_worker" {
  function_name = "${local.name}-ownership-attribution-worker"
  role          = aws_iam_role.ownership_attribution_worker.arn
  handler       = "handlers.ownership_attribution_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # Rate-limited (2 req/s default) paginated CloudTrail sweep -- genuinely
  # slower than validation's DB-only work (research.md R-303's own rationale
  # for splitting these into two queues with independent timeout budgets).
  timeout     = 240
  memory_size = 1024

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.ownership_attribution_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
      POWERTOOLS_SERVICE_NAME  = "cloudpulse-ownership-attribution-worker"
      POWERTOOLS_LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.ownership_attribution_worker]
}

resource "aws_lambda_event_source_mapping" "ownership_attribution_worker" {
  event_source_arn = aws_sqs_queue.ownership_attribution.arn
  function_name    = aws_lambda_function.ownership_attribution_worker.arn
  batch_size       = 1
}
