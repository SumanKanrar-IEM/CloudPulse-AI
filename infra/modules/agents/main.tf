# The intelligence layer's runtime (spec 006, T020; FR-003, FR-008, research.md
# R-601, R-605, R-606).
#
# Three pieces: the Bedrock agent that writes the digest, the action-group Lambda
# it reads governance data through, and the worker that invokes it on a schedule
# (scheduler.tf).
#
# **Runtime limitation, stated rather than discovered.** Both Lambdas here are
# VPC-attached because they need Aurora and API Gateway respectively, and the dev
# VPC has no NAT gateway and no Bedrock interface endpoint -- the standing R-407
# gap, twice declined. Everything below deploys cleanly; the
# bedrock-agent-runtime:InvokeAgent call cannot reach AWS from inside the VPC
# until that gap is funded. FR-007a and SC-009 exist so that is a specified,
# tested state rather than an outage: the run is recorded `failed` with its
# reason and the surfaces serve the last valid digest.

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

  # The single source for the agent's instruction and its tool surface. Read from
  # the files rather than restated here: `definition_hash.py` hashes the same two
  # files onto every agent_run row (FR-005, R-608), and a prompt duplicated in
  # Terraform would let the deployed instruction and the recorded hash disagree.
  agents_root       = "${path.module}/../../../agents"
  digest_prompt     = file("${local.agents_root}/prompts/digest.md")
  digest_definition = jsondecode(file("${local.agents_root}/definitions/digest.json"))

  suggester_prompt     = file("${local.agents_root}/prompts/suggester.md")
  suggester_definition = jsondecode(file("${local.agents_root}/definitions/suggester.json"))
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

# --- the digest agent (R-601) -------------------------------------------------

data "aws_iam_policy_document" "bedrock_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["bedrock.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }
  }
}

resource "aws_iam_role" "digest_agent" {
  name               = "${local.name}-digest-agent"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}

data "aws_iam_policy_document" "digest_agent_runtime" {
  statement {
    sid       = "InvokeFoundationModel"
    effect    = "Allow"
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"]
    resources = ["arn:aws:bedrock:${data.aws_region.current.name}::foundation-model/${var.foundation_model}"]
  }

  statement {
    sid       = "ApplyOwnGuardrail"
    effect    = "Allow"
    actions   = ["bedrock:ApplyGuardrail"]
    resources = [aws_bedrock_guardrail.digest.guardrail_arn]
  }
}

resource "aws_iam_role_policy" "digest_agent_runtime" {
  name   = "runtime"
  role   = aws_iam_role.digest_agent.id
  policy = data.aws_iam_policy_document.digest_agent_runtime.json
}

resource "aws_bedrockagent_agent" "digest" {
  agent_name                  = "${local.name}-digest"
  agent_resource_role_arn     = aws_iam_role.digest_agent.arn
  foundation_model            = var.foundation_model
  description                 = local.digest_definition.description
  instruction                 = local.digest_prompt
  idle_session_ttl_in_seconds = local.digest_definition.idleSessionTTLInSeconds

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.digest.guardrail_id
    guardrail_version    = aws_bedrock_guardrail_version.digest.version
  }
}

resource "aws_bedrockagent_agent_action_group" "digest_governance_read" {
  action_group_name          = local.digest_definition.actionGroups[0].name
  agent_id                   = aws_bedrockagent_agent.digest.agent_id
  agent_version              = "DRAFT"
  description                = local.digest_definition.actionGroups[0].description
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = aws_lambda_function.digest_tools.arn
  }

  api_schema {
    payload = jsonencode(local.digest_definition.actionGroups[0].apiSchema)
  }
}

resource "aws_bedrockagent_agent_alias" "digest" {
  agent_alias_name = "live"
  agent_id         = aws_bedrockagent_agent.digest.agent_id
  description      = "The alias the digest worker invokes. Never the DRAFT version."

  depends_on = [aws_bedrockagent_agent_action_group.digest_governance_read]
}

# --- action-group Lambda (R-602) ----------------------------------------------
#
# Reaches the platform's own HTTP API and nothing else: no database credential,
# no AssumeRole into any scanned account, no cloud SDK. Its IAM policy below is
# the proof of that -- there is nothing in it to read data with.

resource "aws_security_group" "digest_tools" {
  name        = "${local.name}-digest-tools"
  description = "Digest action-group Lambda"
  vpc_id      = var.vpc_id

  egress {
    description = "To API Gateway and Cognito, once the R-407 gap is funded."
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_iam_role" "digest_tools" {
  name               = "${local.name}-digest-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "digest_tools_vpc" {
  role       = aws_iam_role.digest_tools.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "digest_tools" {
  name              = "/aws/lambda/${local.name}-digest-tools"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "digest_tools_runtime" {
  # The agent's own app-client secret, and nothing else. Not the database
  # credential, and not the ExternalId secrets every scanning worker holds --
  # FR-056's "no cloud credential" is enforced by what is absent here.
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
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.digest_tools.arn}:*"]
  }
}

resource "aws_iam_role_policy" "digest_tools_runtime" {
  name   = "runtime"
  role   = aws_iam_role.digest_tools.id
  policy = data.aws_iam_policy_document.digest_tools_runtime.json
}

resource "aws_lambda_function" "digest_tools" {
  function_name = "${local.name}-digest-tools"
  role          = aws_iam_role.digest_tools.arn
  handler       = "digest_tools.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 30 # one HTTP call to the platform API, plus a token exchange.
  memory_size   = 256

  filename         = var.package_path
  source_code_hash = var.package_hash

  layers = var.secrets_extension_layer_arn == "" ? [] : [var.secrets_extension_layer_arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.digest_tools.id]
  }

  environment {
    variables = {
      PLATFORM_API_BASE_URL   = var.platform_api_base_url
      COGNITO_TOKEN_ENDPOINT  = var.cognito_token_endpoint
      AGENT_CLIENT_ID         = var.agent_client_id
      AGENT_CLIENT_SECRET_ID  = var.agent_client_secret_arn
      POWERTOOLS_SERVICE_NAME = "cloudpulse-digest-tools"
      POWERTOOLS_LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.digest_tools]
}

resource "aws_lambda_permission" "digest_tools_bedrock" {
  statement_id  = "AllowBedrockAgentInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.digest_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.digest.agent_arn
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
    sid       = "InvokeDigestAgent"
    effect    = "Allow"
    actions   = ["bedrock:InvokeAgent"]
    resources = [aws_bedrockagent_agent_alias.digest.agent_alias_arn]
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
      CLOUDPULSE_AWS_REGION                       = data.aws_region.current.name
      CLOUDPULSE_DB_HOST                          = var.db_host
      CLOUDPULSE_DB_NAME                          = var.db_name
      CLOUDPULSE_DB_USER                          = var.db_user
      CLOUDPULSE_DB_SECRET_ARN                    = var.db_secret_arn
      CLOUDPULSE_DIGEST_AGENT_ID                  = aws_bedrockagent_agent.digest.agent_id
      CLOUDPULSE_DIGEST_AGENT_ALIAS_ID            = aws_bedrockagent_agent_alias.digest.agent_alias_id
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

# --- the suggester agent (T027; S44, FR-011-FR-014, R-601) --------------------
#
# A second agent rather than a second action group on the digest's. The two have
# different prompts, different tool surfaces and different cost profiles -- the
# digest runs once a day, the suggester once per open finding -- and sharing an
# agent would make `agent_run.definition_hash` ambiguous about which instruction
# produced a given output (FR-005).
#
# The guardrail is shared with the digest deliberately. It encodes a property of
# the tenant's data rather than of a capability: the same resource tags and SDA
# names reach both, and a second guardrail would be a second thing to keep in
# step for no stated difference.

resource "aws_iam_role" "suggester_agent" {
  name               = "${local.name}-suggester-agent"
  assume_role_policy = data.aws_iam_policy_document.bedrock_assume.json
}

resource "aws_iam_role_policy" "suggester_agent_runtime" {
  name = "runtime"
  role = aws_iam_role.suggester_agent.id
  # Identical scope to the digest agent's: this one model, this one guardrail.
  policy = data.aws_iam_policy_document.digest_agent_runtime.json
}

resource "aws_bedrockagent_agent" "suggester" {
  agent_name                  = "${local.name}-suggester"
  agent_resource_role_arn     = aws_iam_role.suggester_agent.arn
  foundation_model            = var.foundation_model
  description                 = local.suggester_definition.description
  instruction                 = local.suggester_prompt
  idle_session_ttl_in_seconds = local.suggester_definition.idleSessionTTLInSeconds

  guardrail_configuration {
    guardrail_identifier = aws_bedrock_guardrail.digest.guardrail_id
    guardrail_version    = aws_bedrock_guardrail_version.digest.version
  }
}

resource "aws_bedrockagent_agent_action_group" "suggester_finding_read" {
  action_group_name          = local.suggester_definition.actionGroups[0].name
  agent_id                   = aws_bedrockagent_agent.suggester.agent_id
  agent_version              = "DRAFT"
  description                = local.suggester_definition.actionGroups[0].description
  skip_resource_in_use_check = true

  action_group_executor {
    lambda = aws_lambda_function.suggester_tools.arn
  }

  api_schema {
    payload = jsonencode(local.suggester_definition.actionGroups[0].apiSchema)
  }
}

resource "aws_bedrockagent_agent_alias" "suggester" {
  agent_alias_name = "live"
  agent_id         = aws_bedrockagent_agent.suggester.agent_id
  description      = "The alias the suggester worker invokes. Never the DRAFT version."

  depends_on = [aws_bedrockagent_agent_action_group.suggester_finding_read]
}

# --- suggester action-group Lambda -------------------------------------------
#
# Its own function rather than a second handler on the digest's, so the two
# allowlists cannot be reached through the wrong door: a bug in one capability's
# path list stays inside that capability.

resource "aws_iam_role" "suggester_tools" {
  name               = "${local.name}-suggester-tools"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "suggester_tools_vpc" {
  role       = aws_iam_role.suggester_tools.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_cloudwatch_log_group" "suggester_tools" {
  name              = "/aws/lambda/${local.name}-suggester-tools"
  retention_in_days = var.log_retention_days
}

data "aws_iam_policy_document" "suggester_tools_runtime" {
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
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${aws_cloudwatch_log_group.suggester_tools.arn}:*"]
  }
}

resource "aws_iam_role_policy" "suggester_tools_runtime" {
  name   = "runtime"
  role   = aws_iam_role.suggester_tools.id
  policy = data.aws_iam_policy_document.suggester_tools_runtime.json
}

resource "aws_lambda_function" "suggester_tools" {
  function_name = "${local.name}-suggester-tools"
  role          = aws_iam_role.suggester_tools.arn
  handler       = "suggester_tools.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 30
  memory_size   = 256

  filename         = var.package_path
  source_code_hash = var.package_hash

  layers = var.secrets_extension_layer_arn == "" ? [] : [var.secrets_extension_layer_arn]

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.digest_tools.id]
  }

  environment {
    variables = {
      PLATFORM_API_BASE_URL   = var.platform_api_base_url
      COGNITO_TOKEN_ENDPOINT  = var.cognito_token_endpoint
      AGENT_CLIENT_ID         = var.agent_client_id
      AGENT_CLIENT_SECRET_ID  = var.agent_client_secret_arn
      POWERTOOLS_SERVICE_NAME = "cloudpulse-suggester-tools"
      POWERTOOLS_LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.suggester_tools]
}

resource "aws_lambda_permission" "suggester_tools_bedrock" {
  statement_id  = "AllowBedrockAgentInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.suggester_tools.function_name
  principal     = "bedrock.amazonaws.com"
  source_arn    = aws_bedrockagent_agent.suggester.agent_arn
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
    sid       = "InvokeSuggesterAgent"
    effect    = "Allow"
    actions   = ["bedrock:InvokeAgent"]
    resources = [aws_bedrockagent_agent_alias.suggester.agent_alias_arn]
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
      CLOUDPULSE_ENVIRONMENT              = var.environment
      CLOUDPULSE_AWS_REGION               = data.aws_region.current.name
      CLOUDPULSE_DB_HOST                  = var.db_host
      CLOUDPULSE_DB_NAME                  = var.db_name
      CLOUDPULSE_DB_USER                  = var.db_user
      CLOUDPULSE_DB_SECRET_ARN            = var.db_secret_arn
      CLOUDPULSE_SUGGESTER_AGENT_ID       = aws_bedrockagent_agent.suggester.agent_id
      CLOUDPULSE_SUGGESTER_AGENT_ALIAS_ID = aws_bedrockagent_agent_alias.suggester.agent_alias_id
      CLOUDPULSE_AGENT_COST_CAP_UNITS     = var.agent_cost_cap_units
      POWERTOOLS_SERVICE_NAME             = "cloudpulse-suggester-worker"
      POWERTOOLS_LOG_LEVEL                = "INFO"
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
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
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
    resources = ["arn:aws:secretsmanager:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:secret:cloudpulse/external-id/*"]
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
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
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
