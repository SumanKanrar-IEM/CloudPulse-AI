# Cognito user pool — federated sign-in, roles from directory groups (S5).
#
# Principle III / FR-031: the platform holds no passwords and exposes no self-service
# registration. `allow_admin_create_user_only = true` is what enforces that at the pool
# level — without it Cognito offers public sign-up by default, which would be an FR-031
# violation shipped by omission.

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

resource "aws_cognito_user_pool" "this" {
  name = local.name

  # FR-031: no self-service registration. Users are created by an administrator in the
  # directory, never by signing up.
  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  password_policy {
    minimum_length                   = 14
    require_lowercase                = true
    require_uppercase                = true
    require_numbers                  = true
    require_symbols                  = true
    temporary_password_validity_days = 1
  }

  account_recovery_setting {
    recovery_mechanism {
      name     = "verified_email"
      priority = 1
    }
  }

  # research.md R-004, layer 1: stamps a single role claim when the group membership is
  # unambiguous, and stamps nothing otherwise. The API re-derives and re-checks on every
  # request regardless (layer 2) -- it never trusts this claim.
  dynamic "lambda_config" {
    for_each = var.pre_token_lambda_arn == "" ? [] : [1]
    content {
      pre_token_generation = var.pre_token_lambda_arn
    }
  }

  user_pool_add_ons {
    advanced_security_mode = var.environment == "prod" ? "ENFORCED" : "AUDIT"
  }
}

# FR-039a: the three groups come from a map variable in terraform.tfvars, so the
# group-to-role mapping is DATA in the versioned definitions and a freshly provisioned
# environment is governed identically to an existing one.
#
# Membership is deliberately NOT managed here. Putting named people in version control
# would make offboarding a pull request, and FR-039 requires the first administrator to
# be established in the directory rather than by the platform.
resource "aws_cognito_user_group" "roles" {
  for_each = var.role_group_map

  name         = each.key
  user_pool_id = aws_cognito_user_pool.this.id
  description  = "Members resolve to the '${each.value}' role (FR-032, FR-039a)."
  # No precedence set, deliberately: precedence exists to break ties between groups,
  # and FR-032a requires a multi-group identity to be REFUSED rather than resolved.
}

resource "aws_cognito_user_pool_client" "web" {
  name         = "${local.name}-web"
  user_pool_id = aws_cognito_user_pool.this.id

  # A public SPA client: no secret, because a secret shipped to a browser is not a
  # secret. PKCE covers the authorization-code flow instead.
  generate_secret = false

  # SRP for the browser. ADMIN_USER_PASSWORD_AUTH is admin-gated -- it can only be
  # called with AWS IAM credentials, so it adds no public attack surface -- and it is
  # what lets the role matrix (SC-008) be verified against a REAL pool rather than only
  # against locally-signed tokens.
  explicit_auth_flows = [
    "ALLOW_REFRESH_TOKEN_AUTH",
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_ADMIN_USER_PASSWORD_AUTH",
  ]

  allowed_oauth_flows                  = ["code"]
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = var.callback_urls
  logout_urls   = var.logout_urls

  # FR-036 / FR-038 / R-005: a 1-hour access token makes the worst-case delay for a
  # directory group change exactly the 1 hour the spec commits to, and SC-013 measures
  # that. The 8-hour refresh token keeps a working day from requiring repeated sign-ins.
  access_token_validity  = 1
  id_token_validity      = 1
  refresh_token_validity = 8

  token_validity_units {
    access_token  = "hours"
    id_token      = "hours"
    refresh_token = "hours"
  }

  # FR-037: signing out must render the session unusable.
  enable_token_revocation = true

  # Do not reveal whether an account exists during authentication -- the same reasoning
  # as FR-035 applies to the login form.
  prevent_user_existence_errors = "ENABLED"

  read_attributes  = ["email", "name"]
  write_attributes = ["name"]
}

resource "aws_cognito_user_pool_domain" "this" {
  domain       = "${local.name}-${var.account_id}"
  user_pool_id = aws_cognito_user_pool.this.id
}
