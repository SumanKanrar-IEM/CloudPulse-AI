# GitHub OIDC federation — constitution Principle III (NON-NEGOTIABLE).
#
# CI/CD authenticates to AWS with short-lived, federated credentials only (FR-022).
# There is no IAM user, no access key, and no AWS secret stored in GitHub. The single
# repository variable this produces is a role *ARN* — an identifier, not a credential.

# The OIDC provider is an ACCOUNT-WIDE singleton: AWS refuses a second
# `aws_iam_openid_connect_provider` for the same URL in one account. Bootstrap has no
# backend of its own (see the note at the top of main.tf), so its state is local to
# whoever runs it -- which means a naive second run, for a second environment, using
# a fresh local state would try to CREATE a duplicate provider and fail, or worse, if
# accidentally pointed at the FIRST environment's state file, would rename and replace
# resources that environment's live deploy role depends on.
#
# `create_oidc_provider` breaks that: true (the default, for the first environment
# bootstrapped in an account) creates it; false (every environment after the first)
# looks the existing one up by URL instead. Both branches resolve to the same
# `local.oidc_provider_arn`, so nothing downstream needs to know which happened.
data "tls_certificate" "github" {
  count = var.create_oidc_provider ? 1 : 0
  url   = "https://token.actions.githubusercontent.com/.well-known/openid-configuration"
}

resource "aws_iam_openid_connect_provider" "github" {
  count           = var.create_oidc_provider ? 1 : 0
  url             = "https://token.actions.githubusercontent.com"
  client_id_list  = ["sts.amazonaws.com"]
  thumbprint_list = [data.tls_certificate.github[0].certificates[0].sha1_fingerprint]
}

data "aws_iam_openid_connect_provider" "existing" {
  count = var.create_oidc_provider ? 0 : 1
  url   = "https://token.actions.githubusercontent.com"
}

locals {
  oidc_provider_arn = var.create_oidc_provider ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.existing[0].arn
}

data "aws_iam_policy_document" "deploy_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_provider_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Scope the trust to this repository AND to the trunk / its environment only.
    #
    # Without the `sub` condition any repository on GitHub could assume this role.
    # Constitution Principle VII makes `pods/pod73` the only long-lived branch, so
    # the trust is narrowed to it — a pull request from a fork cannot deploy.
    # Listed in BOTH the plain repo:OWNER/REPO:... form and GitHub's current default
    # immutable-ID form repo:OWNER@OWNER_ID/REPO@REPO_ID:... (see the owner/repo id
    # variables in main.tf for why). A trust policy written for only the old form is
    # silently rejected by STS with no indication the claim format is the mismatch.
    condition {
      test     = "StringLike"
      variable = "token.actions.githubusercontent.com:sub"
      values = compact([
        "repo:${var.github_repository}:ref:refs/heads/pods/pod73",
        "repo:${var.github_repository}:environment:${var.environment}",
        var.github_owner_id != "" && var.github_repo_id != "" ? (
          "repo:${split("/", var.github_repository)[0]}@${var.github_owner_id}/${split("/", var.github_repository)[1]}@${var.github_repo_id}:ref:refs/heads/pods/pod73"
        ) : "",
        var.github_owner_id != "" && var.github_repo_id != "" ? (
          "repo:${split("/", var.github_repository)[0]}@${var.github_owner_id}/${split("/", var.github_repository)[1]}@${var.github_repo_id}:environment:${var.environment}"
        ) : "",
      ])
    }
  }
}

resource "aws_iam_role" "deploy" {
  name                 = "cloudpulse-${var.environment}-github-deploy"
  assume_role_policy   = data.aws_iam_policy_document.deploy_assume_role.json
  max_session_duration = 3600
}

# Least-privilege, defined in deploy_policy.tf. Replaces PowerUserAccess: scoped to
# the services the pipeline provisions, with IAM limited to cloudpulse-* names and
# explicit denies against destroying the bootstrap foundation or self-escalating.
resource "aws_iam_role_policy_attachment" "deploy" {
  role       = aws_iam_role.deploy.name
  policy_arn = aws_iam_policy.deploy.arn
}

output "deploy_role_arn" {
  value       = aws_iam_role.deploy.arn
  description = "Record as the AWS_DEPLOY_ROLE_ARN repository *variable*, not a secret: it is an identifier, not a credential."
}
