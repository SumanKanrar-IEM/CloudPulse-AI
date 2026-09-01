# API Gateway HTTP API + the API and migration Lambdas (FR-047, FR-016).

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

# --- Lambda networking -----------------------------------------------------
# Both functions sit in the same private subnets as Aurora. The migration Lambda
# exists precisely because a GitHub runner cannot reach those subnets (R-002).

resource "aws_security_group" "lambda" {
  name        = "${local.name}-lambda"
  description = "API and migration Lambdas"
  vpc_id      = var.vpc_id

  egress {
    description = "To Aurora and to AWS APIs via VPC endpoints"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

# --- Execution role --------------------------------------------------------

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

resource "aws_iam_role" "lambda" {
  name               = "${local.name}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
}

resource "aws_iam_role_policy_attachment" "lambda_vpc" {
  role       = aws_iam_role.lambda.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Principle III: the database password is fetched at runtime through this role and is
# never stored. Scoped to the one secret rather than granting secretsmanager:* .
data "aws_iam_policy_document" "lambda_runtime" {
  statement {
    sid       = "ReadDatabaseCredential"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue", "secretsmanager:DescribeSecret"]
    resources = [var.db_secret_arn]
  }

  # spec 002, T048: POST /accounts/{id}/scans starts an execution of the platform's
  # own scan state machine -- platform infrastructure, not a scanned account.
  statement {
    sid       = "StartScanExecutions"
    effect    = "Allow"
    actions   = ["states:StartExecution"]
    resources = [var.scan_state_machine_arn]
  }

  statement {
    sid    = "WriteOwnLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = [
      "${aws_cloudwatch_log_group.api.arn}:*",
      "${aws_cloudwatch_log_group.migrate.arn}:*",
      "${aws_cloudwatch_log_group.pre_token.arn}:*",
    ]
  }
}

resource "aws_iam_role_policy" "lambda_runtime" {
  name   = "runtime"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_runtime.json
}

# --- Log groups. Retention comes from the shared value, never hardcoded (T044).
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${local.name}-api"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "migrate" {
  name              = "/aws/lambda/${local.name}-migrate"
  retention_in_days = var.log_retention_days
}

# --- Functions -------------------------------------------------------------

resource "aws_lambda_function" "api" {
  function_name = "${local.name}-api"
  role          = aws_iam_role.lambda.arn
  handler       = "handlers.api_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 30
  memory_size   = 1024

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT            = var.environment
      CLOUDPULSE_AWS_REGION             = data.aws_region.current.name
      CLOUDPULSE_DB_HOST                = var.db_host
      CLOUDPULSE_DB_NAME                = var.db_name
      CLOUDPULSE_DB_USER                = var.db_user
      CLOUDPULSE_DB_SECRET_ARN          = var.db_secret_arn
      CLOUDPULSE_COGNITO_USER_POOL_ID   = var.cognito_user_pool_id
      CLOUDPULSE_COGNITO_CLIENT_ID      = var.cognito_client_id
      CLOUDPULSE_GIT_SHA                = var.git_sha
      CLOUDPULSE_SCAN_STATE_MACHINE_ARN = var.scan_state_machine_arn
      # Found live (spec 004 T032c): the `$default` route's custom authorizer sends
      # every OPTIONS preflight through to this Lambda rather than API Gateway
      # short-circuiting it, and with no CORS handling in the app itself, Starlette
      # 405'd every preflight. `app/api/main.py` adds `CORSMiddleware` when this is
      # set -- the same origin `cors_configuration` above already restricts to.
      CLOUDPULSE_FRONTEND_URL = var.allowed_origins[0]
      # No credential here, by construction. Only references.
      POWERTOOLS_SERVICE_NAME = "cloudpulse-api"
      POWERTOOLS_LOG_LEVEL    = "INFO"
    }
  }

  depends_on = [aws_cloudwatch_log_group.api]
}

resource "aws_lambda_function" "migrate" {
  function_name = "${local.name}-migrate"
  role          = aws_iam_role.lambda.arn
  handler       = "handlers.migrate_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  # Migrations against a populated store take longer than a request. 15 minutes is
  # the Lambda ceiling; a migration that needs more belongs in a maintenance window.
  timeout     = 900
  memory_size = 1024

  filename         = var.package_path
  source_code_hash = var.package_hash

  vpc_config {
    subnet_ids         = var.private_subnet_ids
    security_group_ids = [aws_security_group.lambda.id]
  }

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT   = var.environment
      CLOUDPULSE_AWS_REGION    = data.aws_region.current.name
      CLOUDPULSE_DB_HOST       = var.db_host
      CLOUDPULSE_DB_NAME       = var.db_name
      CLOUDPULSE_DB_USER       = var.db_user
      CLOUDPULSE_DB_SECRET_ARN = var.db_secret_arn
    }
  }

  depends_on = [aws_cloudwatch_log_group.migrate]
}

# --- HTTP API --------------------------------------------------------------

resource "aws_apigatewayv2_api" "this" {
  name          = local.name
  protocol_type = "HTTP"

  cors_configuration {
    # FR-047: the deployed frontend must reach the API from a browser with no manual
    # configuration. Scoped to the CloudFront origin, never "*".
    allow_origins     = var.allowed_origins
    allow_methods     = ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    allow_headers     = ["authorization", "content-type", "x-correlation-id"]
    expose_headers    = ["x-correlation-id"]
    allow_credentials = false
    max_age           = 300
  }
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.this.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

# --- Lambda authorizer (FR-034, FR-043, R-004 layer 0) ---------------------
#
# A Lambda authorizer, not API Gateway's native "JWT" type, because HTTP APIs give the
# native type no way to customise its 401 -- every rejected token got API Gateway's
# fixed `{"message":"Unauthorized"}` instead of FR-043's uniform envelope (found during
# T107/T109 live prod verification). handlers/authorizer_handler.py verifies signature,
# issuer, audience/client-id and expiry itself -- the same checks the native authorizer
# performed -- then always returns isAuthorized=true, carrying the verification result in
# `context.valid` instead of denying at the gateway. A failed verification therefore
# reaches the app with no claims, and app.core.security.get_principal raises the app's
# own AppError(UNAUTHORIZED) -- the same envelope every other failure already uses. It
# does NOT evaluate claim cardinality either -- app/core/security.py still re-derives the
# role from the raw group claim on every request and refuses anything that is not
# exactly one group (FR-032a).
resource "aws_cloudwatch_log_group" "authorizer" {
  name              = "/aws/lambda/${local.name}-authorizer"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_function" "authorizer" {
  function_name = "${local.name}-authorizer"
  role          = aws_iam_role.lambda.arn
  handler       = "handlers.authorizer_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 5
  memory_size   = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  # Deliberately NOT in the VPC, like the pre-token Lambda: it only needs to reach
  # Cognito's public JWKS endpoint, and putting it in private subnets would need a NAT
  # gateway paid for by every request just to fetch a JWT (R-003's zero-cost posture).

  environment {
    variables = {
      CLOUDPULSE_COGNITO_ISSUER    = var.cognito_user_pool_endpoint
      CLOUDPULSE_COGNITO_CLIENT_ID = var.cognito_client_id
      POWERTOOLS_SERVICE_NAME      = "cloudpulse-authorizer"
    }
  }

  depends_on = [aws_cloudwatch_log_group.authorizer]
}

resource "aws_lambda_permission" "authorizer_invoke" {
  count = var.enable_cognito_auth ? 1 : 0

  statement_id  = "AllowAPIGatewayAuthorizerInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.authorizer.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/authorizers/*"
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  count = var.enable_cognito_auth ? 1 : 0

  api_id                            = aws_apigatewayv2_api.this.id
  authorizer_type                   = "REQUEST"
  authorizer_uri                    = aws_lambda_function.authorizer.invoke_arn
  authorizer_payload_format_version = "2.0"
  enable_simple_responses           = true
  name                              = "${local.name}-cognito"

  # Deliberately empty, not ["$request.header.Authorization"]. HTTP APIs only invoke a
  # REQUEST authorizer when every declared identity source is present -- a request with
  # NO Authorization header at all would never reach the Lambda and would get API
  # Gateway's own fixed 401 again, defeating the whole point of this authorizer (found
  # live against a real deployment: a missing header still returned
  # `{"message":"Unauthorized"}` after the authorizer swap, while an invalid token
  # correctly returned the uniform envelope). Every request must reach the function so
  # "no token" gets the same `context.valid: "false"` treatment as "bad token".
  identity_sources = []

  # An empty identity source disables response caching regardless of this value (there
  # is no cache key to keyed on) -- set to 0 rather than left non-zero and silently
  # ignored.
  authorizer_result_ttl_in_seconds = 0
}

# FR-033a: /health is the ONE unauthenticated operation. Declared explicitly rather
# than relying on a default, so adding a route cannot accidentally make it public.
resource "aws_apigatewayv2_route" "health" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "GET /health"
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = "NONE"
}

# Everything else. There is no default-permit: an endpoint added by a later spec
# inherits the authorizer because it falls through to this route.
resource "aws_apigatewayv2_route" "default" {
  api_id             = aws_apigatewayv2_api.this.id
  route_key          = "$default"
  target             = "integrations/${aws_apigatewayv2_integration.api.id}"
  authorization_type = var.enable_cognito_auth ? "CUSTOM" : "NONE"
  authorizer_id      = var.enable_cognito_auth ? aws_apigatewayv2_authorizer.cognito[0].id : null
}

# --- Pre-token-generation Lambda (R-004 layer 1) ---------------------------
resource "aws_lambda_function" "pre_token" {
  function_name = "${local.name}-pre-token"
  role          = aws_iam_role.lambda.arn
  handler       = "handlers.pre_token_handler.handler"
  runtime       = "python3.12"
  architectures = ["arm64"]
  timeout       = 5
  memory_size   = 512

  filename         = var.package_path
  source_code_hash = var.package_hash

  # Deliberately NOT in the VPC: it needs no database access, and keeping it out
  # avoids adding ENI cold-start latency to every sign-in.

  environment {
    variables = {
      CLOUDPULSE_ENVIRONMENT    = var.environment
      CLOUDPULSE_GROUP_ROLE_MAP = var.group_role_map_encoded
      POWERTOOLS_SERVICE_NAME   = "cloudpulse-pre-token"
    }
  }

  depends_on = [aws_cloudwatch_log_group.pre_token]
}

resource "aws_cloudwatch_log_group" "pre_token" {
  name              = "/aws/lambda/${local.name}-pre-token"
  retention_in_days = var.log_retention_days
}

resource "aws_lambda_permission" "cognito_invoke" {
  count = var.enable_cognito_auth ? 1 : 0

  statement_id  = "AllowCognitoInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.pre_token.function_name
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = var.cognito_user_pool_arn
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.this.id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api.arn
    # `requestId` is API Gateway's own id, always populated -- unlike the field this
    # replaced (`$context.error.messageString`, which is empty outside a gateway-level
    # error and logged "-" on every normal request, found during T107/T109 live prod
    # verification). It is deliberately NOT called "correlationId": that is the app's
    # own generated id (FR-044), which HTTP API access logs have no way to read back
    # from the integration response. app.api.middleware logs this same requestId
    # alongside the app's correlation_id (from the aws.event requestContext) so the two
    # log groups can still be cross-referenced by a shared field for SC-010.
    format = jsonencode({
      requestId    = "$context.requestId"
      httpMethod   = "$context.httpMethod"
      path         = "$context.path"
      status       = "$context.status"
      responseTime = "$context.responseLatency"
    })
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.this.execution_arn}/*/*"
}
