# Network — VPC with private subnets and no NAT gateway.
#
# Aurora and the Lambdas that reach it sit in private subnets. Outbound AWS API
# access goes through VPC endpoints rather than a NAT gateway: cheaper, and it keeps
# traffic to Secrets Manager and S3 off the public internet entirely.

terraform {
  required_version = ">= 1.15.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

variable "environment" {
  type = string
  validation {
    condition     = contains(["dev", "prod"], var.environment)
    error_message = "FR-002 permits exactly two environments: dev and prod."
  }
}

variable "vpc_cidr" {
  type    = string
  default = "10.0.0.0/16"
}

variable "azs" {
  type        = list(string)
  description = "Availability zones. Two minimum: Aurora requires a subnet group spanning at least two."
  default     = ["us-east-1a", "us-east-1b"]

  validation {
    condition     = length(var.azs) >= 2
    error_message = "Aurora requires a DB subnet group spanning at least two availability zones."
  }
}

locals {
  name = "cloudpulse-${var.environment}"
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = local.name }
}

resource "aws_subnet" "private" {
  count             = length(var.azs)
  vpc_id            = aws_vpc.this.id
  cidr_block        = cidrsubnet(var.vpc_cidr, 8, count.index)
  availability_zone = var.azs[count.index]
  tags              = { Name = "${local.name}-private-${count.index}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${local.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# --- VPC endpoints: reach AWS APIs without a NAT gateway -------------------

resource "aws_security_group" "endpoints" {
  name        = "${local.name}-vpce"
  description = "Interface VPC endpoints"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from within the VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr]
  }
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.name}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
}

resource "aws_vpc_endpoint" "secretsmanager" {
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.secretsmanager"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

# --- agent-layer endpoints (spec 006, T029b) ----------------------------------
#
# Off by default, and that is the point. R-604 verified that AWS publishes these
# -- the earlier belief that it did not was a wrong grep, not a platform limit
# (R-604a) -- but publishing and provisioning are different facts, and an
# interface endpoint bills per AZ-hour whether or not anything calls it. The
# standing NAT/endpoint funding decision has been declined twice, so these
# default to off and a deploy that wants them says so explicitly.
#
# `count` rather than `for_each` over a list: these two are not
# interchangeable members of a set. `bedrock-agent-runtime` is what
# `invoke_agent` needs and `execute-api` is what the action groups need to reach
# the platform API, and a future reader should see two named reasons rather than
# a collection to append to without one.

resource "aws_vpc_endpoint" "bedrock_agent_runtime" {
  count               = var.enable_agent_endpoints ? 1 : 0
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.bedrock-agent-runtime"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${local.name}-bedrock-agent-runtime"
  }
}

# Without this the agent reaches Bedrock and its action groups still cannot
# reach the platform API, so it reasons with no tools and produces output that
# fails grounding. The two are only useful together.
resource "aws_vpc_endpoint" "execute_api" {
  count               = var.enable_agent_endpoints ? 1 : 0
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${data.aws_region.current.name}.execute-api"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true

  tags = {
    Name = "${local.name}-execute-api"
  }
}

variable "enable_agent_endpoints" {
  type        = bool
  description = "Provision the bedrock-agent-runtime and execute-api interface endpoints (spec 006, R-604/T029b). Billed per AZ-hour whether or not anything calls them, so this defaults to off and a live-verification window turns it on deliberately. Verified available in us-east-1 across all six AZs; the standing decision not to fund them long-term is unchanged."
  default     = false
}

data "aws_region" "current" {}

output "vpc_id" {
  value = aws_vpc.this.id
}

output "private_subnet_ids" {
  value = aws_subnet.private[*].id
}

output "vpc_cidr" {
  value = aws_vpc.this.cidr_block
}

output "agent_endpoints_enabled" {
  value       = var.enable_agent_endpoints
  description = "Whether the agent-layer interface endpoints are provisioned, so a live-verification write-up can state reachability as a fact rather than an assumption."
}
