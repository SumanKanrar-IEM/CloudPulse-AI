# The digest's daily schedule (spec 006, T020; FR-008, research.md R-605).
#
# One rule, carrying no per-tenant or per-finding knowledge -- the worker asks
# "what is notable today?" itself, the same shape scan/scheduler.tf and
# cost/scheduler.tf already use. A schedule that named its subjects would need
# editing every time a tenant or an account appeared.

data "aws_iam_policy_document" "scheduler_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["scheduler.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "scheduler" {
  name               = "${local.name}-agents-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_runtime" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.digest_worker.arn,
      aws_lambda_function.suggester_worker.arn,
    ]
  }
}

resource "aws_iam_role_policy" "scheduler_runtime" {
  name   = "invoke-workers"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_runtime.json
}

resource "aws_scheduler_schedule" "digest_daily" {
  name       = "${local.name}-digest-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.digest_schedule_expression

  target {
    arn      = aws_lambda_function.digest_worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_daily" })

    # One retry, not the two every other worker takes. A retried digest run
    # spends its token budget again for the same day, and a transient Bedrock
    # error is more likely to still be there a second later than a transient
    # database one (research.md R-606: the model call is the dominant cost).
    retry_policy {
      maximum_retry_attempts = 1
    }
  }
}

# T027. After the digest, not before. Both read the same findings, and a
# suggester pass holding the table while the digest tries to summarise it buys
# nothing -- the digest reports on findings, not on their suggestions.
resource "aws_scheduler_schedule" "suggester_daily" {
  name       = "${local.name}-suggester-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.suggester_schedule_expression

  target {
    arn      = aws_lambda_function.suggester_worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_daily" })

    # No retries at all, unlike the digest's one. A suggester pass is resumable
    # by design -- FR-011's coverage is reached across runs, and whatever this
    # pass wrote is already stored (FR-004a). Retrying would re-spend budget to
    # reach findings tomorrow's pass will reach anyway.
    retry_policy {
      maximum_retry_attempts = 0
    }
  }
}
