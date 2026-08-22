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
      CLOUDPULSE_ENVIRONMENT          = var.environment
      CLOUDPULSE_AWS_REGION           = data.aws_region.current.name
      CLOUDPULSE_DB_HOST              = var.db_host
      CLOUDPULSE_DB_NAME              = var.db_name
      CLOUDPULSE_DB_USER              = var.db_user
      CLOUDPULSE_DB_SECRET_ARN        = var.db_secret_arn
      CLOUDPULSE_COGNITO_USER_POOL_ID = var.cognito_user_pool_id
      CLOUDPULSE_COGNITO_CLIENT_ID    = var.cognito_client_id
      CLOUDPULSE_GIT_SHA              = var.git_sha
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

# --- JWT authorizer (FR-034, R-004 layer 0) --------------------------------
#
# Validates signature, issuer, audience and expiry. It does NOT evaluate claim
# cardinality -- which is exactly why app/core/security.py re-derives the role from the
# raw group claim on every request and refuses anything that is not exactly one group
# (FR-032a). The authorizer alone cannot satisfy that requirement.
resource "aws_apigatewayv2_authorizer" "cognito" {
  count = var.enable_cognito_auth ? 1 : 0

  api_id           = aws_apigatewayv2_api.this.id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "${local.name}-cognito"

  jwt_configuration {
    audience = [var.cognito_client_id]
    issuer   = var.cognito_user_pool_endpoint
  }
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
  authorization_type = var.enable_cognito_auth ? "JWT" : "NONE"
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
    # Includes the correlation id so an access-log line ties to an application log
    # line (SC-010).
    format = jsonencode({
      requestId     = "$context.requestId"
      correlationId = "$context.error.messageString"
      httpMethod    = "$context.httpMethod"
      path          = "$context.path"
      status        = "$context.status"
      responseTime  = "$context.responseLatency"
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
