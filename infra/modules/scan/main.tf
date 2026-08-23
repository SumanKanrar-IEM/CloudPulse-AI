# Scan orchestration: Step Functions state machine, EventBridge Scheduler daily
# rule, and the scan-worker Lambda that does discovery/enrichment/persistence per
# unit of work (spec 002, T042).

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

  # A predictable name/ARN, computed rather than read from the state machine
  # resource's own `.arn` attribute: the worker Lambda's env var needs this ARN
  # (to start executions for the daily trigger and, indirectly, the on-demand
  # trigger reuses it from the API Lambda), and the state machine resource's
  # `definition_substitutions` needs the Lambda's ARN -- referencing each other's
  # resource attributes directly would be a Terraform dependency cycle. Both sides
  # instead agree on this locally-computed value.
  scan_state_machine_name = "${local.name}-scan"
  scan_state_machine_arn  = "arn:aws:states:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:stateMachine:${local.scan_state_machine_name}"
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

# --- Worker Lambda -----------------------------------------------------------

resource "aws_security_group" "worker" {
  name        = "${local.name}-scan-worker"
  description = "Scan-worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora, cross-account scanner roles, and AWS APIs"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

data "aws_iam_policy_document" "worker_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.name}-scan-worker"
  assume_role_policy = data.aws_iam_policy_document.worker_assume.json
}

resource "aws_iam_role_policy_attachment" "worker_vpc" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

data "aws_iam_policy_document" "worker_runtime" {
  # Principle III: the platform's own DB credential, read the same way the API
  # Lambda reads it.
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # FR-003a/research.md R-206: the platform-generated ExternalId this spec stores
  # for cross-account accounts, scoped to this spec's own secret naming convention
  # (connectors/aws.py::store_external_id) -- never a scanned account's own secrets.
  statement {
    sid       = "ReadExternalIdSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:cloudpulse/external-id/*"]
  }

  # research.md R-206: assume the target account's scanner role, once per unit of
  # work. Scoped to the fixed role name cross_account_template.yaml (T017) creates
  # -- this Lambda can never assume an arbitrary role in any account.
  statement {
    sid       = "AssumeScannerRole"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/cloudpulse-scanner"]
  }

  # FR-028: the raw immutable snapshot per unit of work.
  statement {
    sid       = "WriteSnapshots"
    effect    = "Allow"
    actions   = ["s3:PutObject"]
    resources = ["${var.snapshot_bucket_arn}/scans/*"]
  }

  # The `trigger_daily` action starts an execution of this spec's OWN state
  # machine (FR-026) -- platform infrastructure, not a scanned account.
  statement {
    sid       = "StartOwnExecutions"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [local.scan_state_machine_arn]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_runtime.json
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/aws/lambda/${local.name}-scan-worker"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "worker" {
  function_name = "${local.name}-scan-worker"
  role          = aws_iam_role.worker.arn
  handler       = "handlers.scan_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # A large account's discovery + enrichment sweep for one region can legitimately
  # run long (Edge Cases: tens of thousands of resources) -- Step Functions' own
  # bounded retry (FR-024) is what recovers from a timeout, not a longer timeout
  # alone, but 300s leaves real headroom before that matters at demo scale.
  timeout     = 300
  memory_size = 1024

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT            = var.environment
      CLOUDPULSE_AWS_REGION             = data.aws_region.current.name
      CLOUDPULSE_DB_HOST                = var.db_host
      CLOUDPULSE_DB_NAME                = var.db_name
      CLOUDPULSE_DB_USER                = var.db_user
      CLOUDPULSE_DB_SECRET_ARN          = var.db_secret_arn
      CLOUDPULSE_SNAPSHOT_BUCKET        = var.snapshot_bucket_name
      CLOUDPULSE_SCAN_STATE_MACHINE_ARN = local.scan_state_machine_arn
      POWERTOOLS_SERVICE_NAME           = "cloudpulse-scan-worker"
      POWERTOOLS_LOG_LEVEL              = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.worker]
}

# --- State machine (FR-023, research.md R-211) --------------------------------

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "sfn" {
  name               = "${local.name}-scan-sfn"
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
}

data "aws_iam_policy_document" "sfn_runtime" {
  statement {
    sid       = "InvokeWorker"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.worker.arn]
  }
  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "sfn_runtime" {
  name   = "runtime"
  role   = aws_iam_role.sfn.id
  policy = data.aws_iam_policy_document.sfn_runtime.json
}

resource "aws_cloudwatch_log_group" "sfn" {
  name              = "/aws/vendedlogs/states/${local.scan_state_machine_name}"
  retention_in_days = var.log_retention_days
}

resource "aws_sfn_state_machine" "scan" {
  name     = local.scan_state_machine_name
  role_arn = aws_iam_role.sfn.arn

  # T042: the ASL definition lives in its own file, never inlined as a heredoc --
  # that separation is what makes ops/scripts/check_stepfunctions_asl.py's offline
  # validation possible without parsing HCL (T042a). templatefile(), not file():
  # aws_sfn_state_machine has no `definition_substitutions` argument in provider
  # 5.100.0 (confirmed against the installed provider's schema -- this was assumed
  # from CloudFormation's DefinitionSubstitutions property, which the Terraform
  # resource does not mirror). The ${WorkerLambdaArn} placeholder is still a plain,
  # valid JSON string in the committed file either way, so T042a's checker validates
  # the exact same committed content regardless of which function reads it.
  definition = templatefile("${path.module}/scan_workflow.asl.json", {
    WorkerLambdaArn = aws_lambda_function.worker.arn
  })

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.sfn.arn}:*"
    include_execution_data = true
    level                  = "ERROR"
  }

  depends_on = [aws_iam_role_policy.sfn_runtime]
}
