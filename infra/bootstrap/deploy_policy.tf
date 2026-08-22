# Least-privilege policy for the GitHub OIDC deploy role.
#
# Replaces the AWS-managed PowerUserAccess, which grants nearly everything except IAM.
# This role is assumable by anything that can push to pods/pod73, so its blast radius
# is the blast radius of a compromised trunk. On a cloud-governance platform, shipping
# it over-permissioned would be the first finding the product itself would raise.
#
# Structure: allow the services the pipeline provisions, scope IAM to cloudpulse-*
# names, then explicitly DENY the two things that would let a compromised pipeline
# entrench itself -- destroying its own foundation, and escalating to admin.

data "aws_iam_policy_document" "deploy" {

  # --- Services the pipeline provisions (plan.md). Service-scoped, not account-wide.
  statement {
    sid    = "ProvisionPlatformServices"
    effect = "Allow"
    actions = [
      "s3:*",             # state, frontend origin, raw scan snapshots
      "dynamodb:*",       # state lock
      "rds:*",            # Aurora Serverless v2 + RDS Proxy
      "secretsmanager:*", # DB credential (Principle III -- fetched, never stored)
      "lambda:*",         # api, migrate, pre-token, action-group handlers
      "apigateway:*",     # HTTP API + JWT authorizer
      "cognito-idp:*",    # user pool, groups, app client
      "cloudfront:*",     # SPA distribution + OAC
      "logs:*",           # log groups + 30-day retention (FR-046a)
      "cloudwatch:*",     # dashboard + alarms (S7, P2)
      "sns:*",            # alert topic (S7, P2)
      "sqs:*",            # worker queues + DLQs
      "states:*",         # Step Functions scan orchestration
      "scheduler:*",      # EventBridge Scheduler daily scans
      "events:*",         # EventBridge rules
      "kms:*",            # encryption keys
      "acm:*",            # CloudFront certificate
      "bedrock:*",        # Bedrock Agents (spec 6) -- the ONLY permitted GenAI runtime
      "application-autoscaling:*",
      "tag:GetResources",
    ]
    resources = ["*"]
  }

  # --- VPC only. Deliberately NOT ec2:*, which would permit launching instances.
  statement {
    sid    = "ManageVpcOnly"
    effect = "Allow"
    actions = [
      "ec2:Describe*",
      "ec2:CreateVpc", "ec2:DeleteVpc", "ec2:ModifyVpcAttribute",
      "ec2:CreateSubnet", "ec2:DeleteSubnet", "ec2:ModifySubnetAttribute",
      "ec2:CreateRouteTable", "ec2:DeleteRouteTable", "ec2:CreateRoute", "ec2:DeleteRoute",
      "ec2:AssociateRouteTable", "ec2:DisassociateRouteTable",
      "ec2:CreateSecurityGroup", "ec2:DeleteSecurityGroup",
      "ec2:AuthorizeSecurityGroupIngress", "ec2:AuthorizeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress", "ec2:RevokeSecurityGroupEgress",
      "ec2:CreateVpcEndpoint", "ec2:DeleteVpcEndpoints", "ec2:ModifyVpcEndpoint",
      "ec2:CreateNetworkInterface", "ec2:DeleteNetworkInterface",
      "ec2:CreateTags", "ec2:DeleteTags",
    ]
    resources = ["*"]
  }

  # --- IAM, scoped to cloudpulse-* names. The pipeline must create Lambda execution
  # --- roles; it must not be able to touch anything else in the account.
  statement {
    sid    = "ManageCloudpulseIamOnly"
    effect = "Allow"
    actions = [
      "iam:CreateRole", "iam:DeleteRole", "iam:GetRole", "iam:UpdateRole",
      "iam:TagRole", "iam:UntagRole", "iam:ListRoleTags",
      "iam:AttachRolePolicy", "iam:DetachRolePolicy", "iam:ListAttachedRolePolicies",
      "iam:PutRolePolicy", "iam:DeleteRolePolicy", "iam:GetRolePolicy", "iam:ListRolePolicies",
      "iam:UpdateAssumeRolePolicy", "iam:PassRole",
      "iam:CreatePolicy", "iam:DeletePolicy", "iam:GetPolicy",
      "iam:CreatePolicyVersion", "iam:DeletePolicyVersion",
      "iam:GetPolicyVersion", "iam:ListPolicyVersions",
    ]
    resources = [
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/cloudpulse-*",
      "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/cloudpulse-*",
    ]
  }

  statement {
    sid       = "ReadOnlyIdentity"
    effect    = "Allow"
    actions   = ["iam:List*", "iam:Get*", "sts:GetCallerIdentity"]
    resources = ["*"]
  }

  # --- DENY 1: the pipeline may not destroy its own foundation.
  #
  # Without this, a bad `terraform destroy` reaching the bootstrap resources would take
  # out the state backend, the lock table and the OIDC trust -- leaving no way to
  # recover except manual console work as root. Deny beats Allow unconditionally.
  statement {
    sid    = "ProtectBootstrapFoundation"
    effect = "Deny"
    actions = [
      "s3:DeleteBucket", "s3:DeleteBucketPolicy", "s3:PutBucketPolicy",
      "dynamodb:DeleteTable",
      "iam:DeleteOpenIDConnectProvider", "iam:UpdateOpenIDConnectProviderThumbprint",
    ]
    resources = [
      aws_s3_bucket.state.arn,
      "${aws_s3_bucket.state.arn}/*",
      aws_dynamodb_table.lock.arn,
      local.oidc_provider_arn,
    ]
  }

  # --- DENY 2: the pipeline may not modify or escalate its own role.
  #
  # Closes the loop where a compromised trunk rewrites the OIDC trust condition to
  # admit any repository, or attaches AdministratorAccess to itself.
  statement {
    sid    = "NoSelfEscalation"
    effect = "Deny"
    actions = [
      "iam:UpdateAssumeRolePolicy", "iam:DeleteRole", "iam:AttachRolePolicy",
      "iam:PutRolePolicy", "iam:DetachRolePolicy",
    ]
    resources = [aws_iam_role.deploy.arn]
  }

  statement {
    sid       = "NoAdminPolicyAttachment"
    effect    = "Deny"
    actions   = ["iam:AttachRolePolicy", "iam:AttachUserPolicy", "iam:AttachGroupPolicy"]
    resources = ["*"]

    condition {
      test     = "ArnLike"
      variable = "iam:PolicyARN"
      values = [
        "arn:aws:iam::aws:policy/AdministratorAccess",
        "arn:aws:iam::aws:policy/PowerUserAccess",
        "arn:aws:iam::aws:policy/IAMFullAccess",
      ]
    }
  }

  # --- DENY 3: no IAM users, ever. Principle III is roles-only; a user means keys.
  statement {
    sid    = "NoIamUsersOrKeys"
    effect = "Deny"
    actions = [
      "iam:CreateUser", "iam:CreateAccessKey", "iam:CreateLoginProfile",
      "iam:UpdateAccessKey", "iam:UpdateLoginProfile",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_policy" "deploy" {
  name        = "cloudpulse-${var.environment}-github-deploy"
  description = "Least-privilege deploy permissions for the GitHub OIDC role (replaces PowerUserAccess)."
  policy      = data.aws_iam_policy_document.deploy.json
}
