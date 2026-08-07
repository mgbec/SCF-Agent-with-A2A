################################################################################
# SCF Data Auto-Updater
#
# Weekly Lambda checks for new SCF releases, downloads the JSON,
# uploads to S3, and triggers Knowledge Base re-ingestion.
# Sends SNS notification on success or failure.
################################################################################

# --------------------------------------------------------------------------
# SNS Topic - Notifications
# --------------------------------------------------------------------------

resource "aws_sns_topic" "scf_updates" {
  name = "${local.name_prefix}-scf-update-notifications"
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notification_email != "" ? 1 : 0
  topic_arn = aws_sns_topic.scf_updates.arn
  protocol  = "email"
  endpoint  = var.notification_email
}

# --------------------------------------------------------------------------
# Lambda Function - SCF Version Checker & Updater
# --------------------------------------------------------------------------

data "archive_file" "scf_updater" {
  type        = "zip"
  source_file = "${path.module}/../lambda/scf_updater/handler.py"
  output_path = "${path.module}/../lambda/scf_updater/package.zip"
}

resource "aws_iam_role" "scf_updater" {
  name = "${local.name_prefix}-scf-updater-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "scf_updater" {
  name = "scf-updater-permissions"
  role = aws_iam_role.scf_updater.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.scf_data.arn,
          "${aws_s3_bucket.scf_data.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:StartIngestionJob",
          "bedrock:ListDataSources"
        ]
        Resource = [
          aws_bedrockagent_knowledge_base.scf.arn,
          "${aws_bedrockagent_knowledge_base.scf.arn}/*"
        ]
      },
      {
        Effect = "Allow"
        Action = [
          "sns:Publish"
        ]
        Resource = aws_sns_topic.scf_updates.arn
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
      {
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter"
        ]
        Resource = "arn:aws:ssm:${local.region}:${local.account_id}:parameter/${local.name_prefix}/scf-current-version"
      }
    ]
  })
}

resource "aws_lambda_function" "scf_updater" {
  function_name    = "${local.name_prefix}-scf-updater"
  description      = "Checks for new SCF releases weekly, downloads JSON, uploads to S3, and triggers KB sync"
  role             = aws_iam_role.scf_updater.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  timeout          = 300
  memory_size      = 512
  filename         = data.archive_file.scf_updater.output_path
  source_code_hash = data.archive_file.scf_updater.output_base64sha256

  environment {
    variables = {
      SCF_DATA_BUCKET   = aws_s3_bucket.scf_data.id
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.scf.id
      SNS_TOPIC_ARN     = aws_sns_topic.scf_updates.arn
      VERSION_PARAM     = "/${local.name_prefix}/scf-current-version"
      SCF_DOWNLOAD_URL  = "https://content.securecontrolsframework.com/json/scf-full.json"
    }
  }

  tags = {
    Component = "scf-updater"
  }
}

# --------------------------------------------------------------------------
# SSM Parameter - Track Current Version
# --------------------------------------------------------------------------

resource "aws_ssm_parameter" "scf_version" {
  name  = "/${local.name_prefix}/scf-current-version"
  type  = "String"
  value = "2026.2"

  lifecycle {
    ignore_changes = [value]
  }
}

# --------------------------------------------------------------------------
# EventBridge Rule - Weekly Schedule
# --------------------------------------------------------------------------

resource "aws_cloudwatch_event_rule" "scf_update_check" {
  name                = "${local.name_prefix}-scf-weekly-check"
  description         = "Checks for new SCF releases every Monday at 8:00 UTC"
  schedule_expression = "cron(0 8 ? * MON *)"

  tags = {
    Component = "scf-updater"
  }
}

resource "aws_cloudwatch_event_target" "scf_updater" {
  rule = aws_cloudwatch_event_rule.scf_update_check.name
  arn  = aws_lambda_function.scf_updater.arn
}

resource "aws_lambda_permission" "eventbridge" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.scf_updater.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.scf_update_check.arn
}

# --------------------------------------------------------------------------
# CloudWatch Log Group (explicit retention)
# --------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "scf_updater" {
  name              = "/aws/lambda/${aws_lambda_function.scf_updater.function_name}"
  retention_in_days = 30

  tags = {
    Component = "scf-updater"
  }
}
