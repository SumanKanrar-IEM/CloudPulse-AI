# EventBridge Scheduler daily rule (FR-026, T043). Invokes the worker Lambda directly
# with a fixed {"action": "trigger_daily"} payload -- the worker itself queries the
# database for which accounts are due and starts one Step Functions execution per
# account (app/scan/orchestrator.start_due_daily_scans), so this rule needs no
# per-account knowledge and never changes as accounts are added or removed.

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
  name               = "${local.name}-scan-scheduler"
  assume_role_policy = data.aws_iam_policy_document.scheduler_assume.json
}

data "aws_iam_policy_document" "scheduler_runtime" {
  statement {
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.worker.arn]
  }
}

resource "aws_iam_role_policy" "scheduler_runtime" {
  name   = "invoke-worker"
  role   = aws_iam_role.scheduler.id
  policy = data.aws_iam_policy_document.scheduler_runtime.json
}

resource "aws_scheduler_schedule" "daily_scan" {
  name       = "${local.name}-daily-scan"
  group_name = "default"

  flexible_time_window {
    mode = "OFF"
  }

  schedule_expression = var.schedule_expression

  target {
    arn      = aws_lambda_function.worker.arn
    role_arn = aws_iam_role.scheduler.arn
    input    = jsonencode({ action = "trigger_daily" })

    retry_policy {
      maximum_retry_attempts = 2
    }
  }
}
