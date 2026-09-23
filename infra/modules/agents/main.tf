# The intelligence layer's runtime (spec 006, T020, T065; FR-003, FR-008,
# research.md R-605, R-606, R-613, R-613a, R-613b).
#
# Three pieces: one Bedrock AgentCore Runtime hosting every agent capability
# (`agents/runtime/main.py`), the guardrail it applies, and the worker Lambdas
# that invoke it on a schedule (scheduler.tf) and validate what comes back.
#
# **Why one runtime.** The capabilities differ only in prompt and tool
# allowlist, both of which the runtime selects per invocation from the payload.
# The cost cap, the grounding validator and the run row are per capability in
# the worker that calls it. Four runtimes would be four copies of one file with
# nothing they could do differently. `agent_run.definition_hash` still hashes
# each capability's own prompt and definition (R-608).
#
# **Why a code zip and not a container.** R-613a: AgentCore deploys a Python
# zip from S3 with no container, no ECR and no Docker -- the artefact packages
# the way every Lambda in this repository already does. The deploy workflow
# builds it with boto3 vendored and every bytecode cache stripped, because the
# managed runtime ships neither boto3 nor tolerance for another Python's
# `__pycache__` (R-613b, both found by trying).
#
# **What R-605's gap still means here.** The runtime runs in PUBLIC network
# mode and reaches the platform API over the internet -- verified (R-613b), so
# the agent's own tool calls need no VPC endpoint. The *workers* are still
# VPC-attached (they need Aurora) and still cannot reach
# `bedrock-agentcore:InvokeAgentRuntime` from inside the VPC until an interface
# endpoint is funded or NAT is added. FR-007a and SC-009 make that a recorded
# run failure, not an outage.
#
# **Why an Amazon-owned model.** Third-party models on Bedrock (Anthropic,
# Cohere, Meta) are AWS Marketplace subscriptions sold by AWS Inc., which an
# AISPL-billed account cannot complete without an international card
# (R-613b). Amazon Nova is first-party: no Marketplace, billed like every
# other AWS service. Principle II names Amazon Bedrock, not a vendor, and
# R-613c verified Nova 2 Lite answers from inside the runtime.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

locals {
  name = "cloudpulse-${var.environment}"

  # The model id lives in the definition files, not here: `definition_hash.py`
  # hashes those files onto every agent_run row (FR-005, R-608), so a model
  # change is a hash change. Terraform reads it back only to scope IAM. Every
  # capability names the same id today; the policy below grants each distinct
  # one it finds, so a definition that moved to a different model would get its
  # grant without an edit here.
  agents_root = "${path.module}/../../../agents"
  model_ids = distinct([
    for capability in ["digest", "suggester", "advisor", "narrator"] :
    jsondecode(file("${local.agents_root}/definitions/${capability}.json")).modelId
  ])
  # `global.amazon.nova-2-lite-v1:0` is an inference profile; the grant
  # needs both the profile and the foundation model it routes to, in every
  # region it may route to (R-613b, run 4).
  foundation_models = [for id in local.model_ids : regex("^[a-z-]+\\.(.*)$", id)[0]]
}

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# --- guardrail (Principle II) -------------------------------------------------
#
# Principle II names guardrails as part of the GenAI layer, not an optional
# extra. The filters below are deliberately modest: the digest's input is this
# tenant's own governance data, so the realistic risk is prompt injection through
# a resource tag or an SDA name someone controls, not the model volunteering
# harmful content unprompted.

resource "aws_bedrock_guardrail" "digest" {
  name                      = "${local.name}-digest"
  blocked_input_messaging   = "This request could not be processed."
  blocked_outputs_messaging = "This response could not be produced."
  description               = "Guardrail for the digest agent (spec 006, Principle II)."

  content_policy_config {
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE" # PROMPT_ATTACK is an input-side filter; AWS rejects any other value.
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "MEDIUM"
      output_strength = "MEDIUM"
    }
  }

  # A resource tag or an owner override can carry an email address, and the
  # digest has no reason to repeat one back.
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
  }
}

resource "aws_bedrock_guardrail_version" "digest" {
  guardrail_arn = aws_bedrock_guardrail.digest.guardrail_arn
  description   = "Pinned so a guardrail edit is a deliberate redeploy, not a silent behaviour change."
}


# --- the agent runtime (T065; R-613, R-613a, R-613b) ---------------------------

# The artefact lives in S3 because that is what AgentCore's code deploy reads
# from. Versioned so the runtime's `version_id` pin is exact, and private.
resource "aws_s3_bucket" "agent_artifacts" {
  bucket        = "${local.name}-agent-artifacts-${data.aws_caller_identity.current.account_id}"
  force_destroy = true
}

resource "aws_s3_bucket_versioning" "agent_artifacts" {
  bucket = aws_s3_bucket.agent_artifacts.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_public_access_block" "agent_artifacts" {
  bucket                  = aws_s3_bucket.agent_artifacts.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_object" "agent_package" {
  bucket = aws_s3_bucket.agent_artifacts.id
  key    = "agent.zip"
  source = var.agent_package_path
  etag   = var.agent_package_hash != "" ? var.agent_package_hash : null

  depends_on = [aws_s3_bucket_versioning.agent_artifacts]
}

data "aws_iam_policy_document" "agentcore_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock-agentcore.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "agent_runtime" {
  name               = "${local.name}-agent-runtime"
  assume_role_policy = data.aws_iam_policy_document.agentcore_assume.json
}

data "aws_iam_policy_document" "agent_runtime" {
  statement {
    sid       = "ReadOwnArtifact"
    effect    = "Allow"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.agent_artifacts.arn}/agent.zip"]
  }

  # The profile *and* the foundation model behind it, in every region the
  # profile routes to. Granting the profile alone is refused at invocation
  # (R-613b). Scoped to the ids the definitions actually name.
  statement {
    sid     = "InvokeModel"
    effect  = "Allow"
    actions = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = concat(
      [for id in local.model_ids : "arn:aws:bedrock:*:${data.aws_caller_identity.current.account_id}:inference-profile/${id}"],
      [for fm in local.foundation_models : "arn:aws:bedrock:*::foundation-model/${fm}"],
    )
  }

  statement {
    sid       = "ApplyGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.digest.guardrail_arn]
  }

  # FR-003: the only secret the agent may read is its own Cognito client
  # secret, and it may read nothing else. No ExternalId, no scanner role.
  dynamic "statement" {
    for_each = var.agent_client_secret_arn == "" ? [] : [var.agent_client_secret_arn]
    content {
      sid       = "ReadOwnClientSecret"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = [statement.value]
    }
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
    resources = ["arn:aws:logs:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"]
  }
}

resource "aws_iam_role_policy" "agent_runtime" {
  name   = "runtime"
  role   = aws_iam_role.agent_runtime.id
  policy = data.aws_iam_policy_document.agent_runtime.json
}

resource "aws_bedrockagentcore_agent_runtime" "this" {
  # AgentCore names allow [a-zA-Z0-9_], no hyphens.
  agent_runtime_name = replace("${local.name}_agents", "-", "_")
  role_arn           = aws_iam_role.agent_runtime.arn
  description        = "CloudPulse intelligence layer: digest, suggester, advisor, narrator (spec 006)."

  agent_runtime_artifact {
    code_configuration {
      code {
        s3 {
          bucket     = aws_s3_bucket.agent_artifacts.id
          prefix     = aws_s3_object.agent_package.key
          version_id = aws_s3_object.agent_package.version_id
        }
      }
      runtime     = "PYTHON_3_12"
      entry_point = ["main.py"]
    }
  }

  # PUBLIC: the runtime reaches the platform API over the internet (R-613b).
  # VPC mode would put the agent's tool calls behind the same endpoint gap the
  # workers already have, for nothing gained.
  network_configuration {
    network_mode = "PUBLIC"
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  environment_variables = {
    PLATFORM_API_BASE_URL  = var.platform_api_base_url
    COGNITO_TOKEN_ENDPOINT = var.cognito_token_endpoint
    AGENT_CLIENT_ID        = var.agent_client_id
    AGENT_CLIENT_SECRET_ID = var.agent_client_secret_arn
    GUARDRAIL_ID           = aws_bedrock_guardrail.digest.guardrail_id
    GUARDRAIL_VERSION      = aws_bedrock_guardrail_version.digest.version
  }

  depends_on = [aws_iam_role_policy.agent_runtime]
}

# Declared, with a retention, so the service does not create it without one.
# R-613a found the runtime creates this group itself on first invocation and
# `delete-agent-runtime` leaves it behind -- the orphan class playbook 0.5.3
# names. Owning it here means `destroy` removes it.
resource "aws_cloudwatch_log_group" "agent_runtime" {
  name              = "/aws/bedrock-agentcore/runtimes/${aws_bedrockagentcore_agent_runtime.this.agent_runtime_id}-DEFAULT"
  retention_in_days = var.log_retention_days
}

# --- digest worker (FR-008) ---------------------------------------------------

resource "aws_security_group" "digest_worker" {
  name        = "${local.name}-digest-worker"
  description = "Digest worker Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora, and to Bedrock once the R-407 gap is funded."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "digest_worker" {
  name               = "${local.name}-digest-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "digest_worker_vpc" {
  role       = aws_iam_role.digest_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "digest_worker" {
  name              = "/aws/lambda/${local.name}-digest-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "digest_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # Scoped to this one alias. A worker permitted to invoke any agent could run
  # the suggester's or the advisor's prompt against the digest's budget, and the
  # agent_run row would name the wrong capability.
  statement {
    sid       = "InvokeAgentRuntime"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn, "${aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn}/runtime-endpoint/*"]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.digest_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "digest_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.digest_worker.id
  policy = data.aws_iam_policy_document.digest_worker_runtime.json
}

resource "aws_lambda_function" "digest_worker" {
  function_name = "${local.name}-digest-worker"
  role          = aws_iam_role.digest_worker.arn
  handler       = "handlers.digest_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # An agent invocation is a multi-step orchestration, not one model call: each
  # action-group round trip is its own reasoning step. Generous, because the run
  # is capped in tokens (FR-004) rather than in wall clock.
  timeout     = 300
  memory_size = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.digest_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT                      = var.environment
      CLOUDPULSE_AWS_REGION                       = data.aws_region.current.region
      CLOUDPULSE_DB_HOST                          = var.db_host
      CLOUDPULSE_DB_NAME                          = var.db_name
      CLOUDPULSE_DB_USER                          = var.db_user
      CLOUDPULSE_DB_SECRET_ARN                    = var.db_secret_arn
      CLOUDPULSE_AGENT_RUNTIME_ARN                = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
      CLOUDPULSE_AGENT_COST_CAP_UNITS             = var.agent_cost_cap_units
      CLOUDPULSE_DIGEST_SPEND_NOTABLE_PERCENT     = var.digest_spend_notable_percent
      CLOUDPULSE_DIGEST_SPEND_NOTABLE_USD         = var.digest_spend_notable_usd
      CLOUDPULSE_DIGEST_COMPLIANCE_NOTABLE_POINTS = var.digest_compliance_notable_points
      POWERTOOLS_SERVICE_NAME                     = "cloudpulse-digest-worker"
      POWERTOOLS_LOG_LEVEL                        = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.digest_worker]
}


# --- suggester worker ---------------------------------------------------------

resource "aws_iam_role" "suggester_worker" {
  name               = "${local.name}-suggester-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "suggester_worker_vpc" {
  role       = aws_iam_role.suggester_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "suggester_worker" {
  name              = "/aws/lambda/${local.name}-suggester-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "suggester_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # Scoped to the suggester's own alias, for the same reason the digest worker
  # is scoped to its own: a worker able to invoke any agent could spend one
  # capability's budget on another's prompt, and the `agent_run` row would name
  # the wrong capability.
  statement {
    sid       = "InvokeAgentRuntime"
    effect    = "Allow"
    actions   = ["bedrock-agentcore:InvokeAgentRuntime"]
    resources = [aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn, "${aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn}/runtime-endpoint/*"]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.suggester_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "suggester_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.suggester_worker.id
  policy = data.aws_iam_policy_document.suggester_worker_runtime.json
}

resource "aws_lambda_function" "suggester_worker" {
  function_name = "${local.name}-suggester-worker"
  role          = aws_iam_role.suggester_worker.arn
  handler       = "handlers.suggester_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # Longer than the digest's: this pass makes one agent invocation per open
  # finding, sequentially. The cost cap (FR-004) is what actually bounds the
  # work -- this only has to be long enough that the cap is what stops it, since
  # a wall-clock timeout would kill the pass without recording an outcome.
  timeout     = 900
  memory_size = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.digest_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT          = var.environment
      CLOUDPULSE_AWS_REGION           = data.aws_region.current.region
      CLOUDPULSE_DB_HOST              = var.db_host
      CLOUDPULSE_DB_NAME              = var.db_name
      CLOUDPULSE_DB_USER              = var.db_user
      CLOUDPULSE_DB_SECRET_ARN        = var.db_secret_arn
      CLOUDPULSE_AGENT_RUNTIME_ARN    = aws_bedrockagentcore_agent_runtime.this.agent_runtime_arn
      CLOUDPULSE_AGENT_COST_CAP_UNITS = var.agent_cost_cap_units
      POWERTOOLS_SERVICE_NAME         = "cloudpulse-suggester-worker"
      POWERTOOLS_LOG_LEVEL            = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.suggester_worker]
}

# --- advisor worker (T038; S43, FR-015, FR-015a, FR-018) ----------------------
#
# A worker and a schedule, and no agent. The advisor run is deterministic --
# `app/governance/advisor.py` says why -- so there is no `aws_bedrockagent_agent`
# here, no alias, no action-group Lambda and no `bedrock:InvokeAgent` grant.
# Deploying an agent nothing invokes would be clutter that reads as a
# capability; the definition files stay in `agents/` as the contract the run
# hashes, and are the seam if narration is ever wanted.
#
# This is also the one spec 006 worker R-605's VPC-reachability gap does not
# touch: it reads the database and writes the database, nothing else.

resource "aws_iam_role" "advisor_worker" {
  name               = "${local.name}-advisor-worker"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "advisor_worker_vpc" {
  role       = aws_iam_role.advisor_worker.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "advisor_worker" {
  name              = "/aws/lambda/${local.name}-advisor-worker"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "advisor_worker_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.advisor_worker.arn}:*"]
  }
}

resource "aws_iam_role_policy" "advisor_worker_runtime" {
  name   = "runtime"
  role   = aws_iam_role.advisor_worker.id
  policy = data.aws_iam_policy_document.advisor_worker_runtime.json
}

resource "aws_lambda_function" "advisor_worker" {
  function_name = "${local.name}-advisor-worker"
  role          = aws_iam_role.advisor_worker.arn
  handler       = "handlers.advisor_worker_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # One grouped query over `resource` and a handful of writes. Nothing here
  # waits on a model.
  timeout     = 120
  memory_size = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids = var.private_subnet_ids
    # The digest worker's group: same egress need (the database), and a third
    # group with identical rules would be a third thing to keep identical.
    security_group_ids = [aws_security_group.digest_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.region
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
      POWERTOOLS_SERVICE_NAME  = "cloudpulse-advisor-worker"
      POWERTOOLS_LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.advisor_worker]
}

# --- metrics collector (T043; S50, FR-019, FR-020, R-606) --------------------
#
# The one P2 cost that grows with inventory. `GetMetricData` is billed per
# metric-datapoint requested, and this worker requests
# resources x metrics x periods every day -- so, unlike everything else in this
# module, its bill tracks the size of the tenant's accounts rather than a fixed
# schedule. Two things bound it, both stated here rather than left implicit:
#
#   * `governance/metrics.py::METRIC_QUERIES` names exactly which metrics are
#     asked for (two for EC2, four for RDS), so the multiplier is small and
#     visible in one place;
#   * one period per day, so the periods term is 1 per run.
#
# Dev posture: identical to prod. At dev's inventory (tens of resources) the
# daily cost is fractions of a cent; the lever that matters is the query list,
# not this module. R-606 asked for the posture to be stated, and that is it.
#
# Same VPC-reachability caveat as the cost worker (R-605): cannot reach
# CloudWatch from inside the VPC until R-407's endpoint gap is funded, and the
# handler's per-account isolation turns that into a logged run, not a crash.

resource "aws_iam_role" "metrics_collector" {
  name               = "${local.name}-metrics-collector"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "metrics_collector_vpc" {
  role       = aws_iam_role.metrics_collector.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "metrics_collector" {
  name              = "/aws/lambda/${local.name}-metrics-collector"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "metrics_collector_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # The same ExternalId read and scanner-role assumption every other
  # account-touching worker carries (R-206). Not a new role, not a wider one.
  statement {
    sid       = "ReadExternalIdSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:secret:cloudpulse/external-id/*"]
  }

  statement {
    sid       = "AssumeScannerRole"
    effect    = "Allow"
    actions   = ["sts:AssumeRole"]
    resources = ["arn:aws:iam::*:role/cloudpulse-scanner"]
  }

  # The one AWS read this worker performs, directly in local mode and through
  # the assumed scanner role otherwise. GetMetricData has no resource-level
  # ARN scoping.
  statement {
    sid       = "GetMetricData"
    effect    = "Allow"
    actions   = ["cloudwatch:GetMetricData"]
    resources = ["*"]
  }

  statement {
    sid       = "WriteOwnLogs"
    effect    = "Allow"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.metrics_collector.arn}:*"]
  }
}

resource "aws_iam_role_policy" "metrics_collector_runtime" {
  name   = "runtime"
  role   = aws_iam_role.metrics_collector.id
  policy = data.aws_iam_policy_document.metrics_collector_runtime.json
}

resource "aws_lambda_function" "metrics_collector" {
  function_name = "${local.name}-metrics-collector"
  role          = aws_iam_role.metrics_collector.arn
  handler       = "handlers.metrics_collector_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # One GetMetricData call per account per region, sequential. Long enough
  # that a tenant with many accounts is bounded by the API, not by this.
  timeout     = 300
  memory_size = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.digest_worker.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.region
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
      POWERTOOLS_SERVICE_NAME  = "cloudpulse-metrics-collector"
      POWERTOOLS_LOG_LEVEL     = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.metrics_collector]
}
