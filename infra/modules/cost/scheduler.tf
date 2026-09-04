# EventBridge Scheduler rules for this module's workers (research.md R-501: each
# worker queries what's due itself; the schedule carries no per-account/per-finding
# knowledge and never changes as accounts/findings come and go, matching
# scan/scheduler.tf's own daily-scan rule exactly). One rule lands per task
# (T009 here; T016 and T047 add their own later).

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
  name               = "${local.name}-cost-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_runtime" {
  statement {
    effect  = "Allow"
    actions = ["lambda:InvokeFunction"]
    resources = [
      aws_lambda_function.cost_ingestion_worker.arn,
      aws_lambda_function.notification_worker.arn,
      aws_lambda_function.iam_hygiene_worker.arn,
    ]
  }
}

resource "aws_iam_role_policy" "scheduler_runtime" {
  name   = "invoke-workers"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_runtime.json
}

resource "aws_scheduler_schedule" "cost_ingestion_daily" {
  name       = "${local.name}-cost-ingestion-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.cost_ingestion_schedule_expression

  target {
    arn      = aws_lambda_function.cost_ingestion_worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_daily" })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# T016. One daily pass, not one rule per cadence point: day-2/day-4 and the day-4
# escalation (T021) are answered by this same invocation, because they are one
# question about one findings table (research.md R-501).
resource "aws_scheduler_schedule" "notification_daily" {
  name       = "${local.name}-notification-daily"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.notification_schedule_expression

  target {
    arn      = aws_lambda_function.notification_worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_daily" })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}

# T047. Weekly, not daily: IAM last-used data changes slowly and the analysis window
# is 90 days, so a daily run would spend seven times the invocations to move a flag at
# most a day sooner (research.md R-510).
resource "aws_scheduler_schedule" "iam_hygiene_weekly" {
  name       = "${local.name}-iam-hygiene-weekly"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.iam_hygiene_schedule_expression

  target {
    arn      = aws_lambda_function.iam_hygiene_worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_weekly" })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
