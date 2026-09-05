################################################################################
# A2A async task model
#
# API Gateway HTTP APIs cap the integration at ~30s, so message/send cannot block
# on a long agent turn. Instead the bridge writes a "submitted" Task and enqueues
# it here; this worker runs the agent out of band and updates the Task to
# working -> completed / failed. The client polls tasks/get on the bridge.
#
#   bridge Lambda --SendMessage--> SQS a2a-tasks --(batch 1)--> worker Lambda
#                                        |                           |
#                                        v (after maxReceiveCount)    v
#                                   SQS a2a-tasks-dlq          InvokeAgentRuntime
#                                                              + DynamoDB updates
################################################################################

# --------------------------------------------------------------------------
# SQS: work queue + dead-letter queue
# --------------------------------------------------------------------------
resource "aws_sqs_queue" "a2a_tasks_dlq" {
  count = local.a2a_enabled ? 1 : 0

  name                      = "${local.name_prefix}-a2a-tasks-dlq"
  message_retention_seconds = 1209600 # 14 days

  tags = { Component = "a2a" }
}

resource "aws_sqs_queue" "a2a_tasks" {
  count = local.a2a_enabled ? 1 : 0

  name                       = "${local.name_prefix}-a2a-tasks"
  visibility_timeout_seconds = var.a2a_worker_timeout + 60
  message_retention_seconds  = 3600 # 1h - a task not picked up within an hour is stale

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.a2a_tasks_dlq[0].arn
    maxReceiveCount     = 2
  })

  tags = { Component = "a2a" }
}

# --------------------------------------------------------------------------
# Worker Lambda
# --------------------------------------------------------------------------
data "archive_file" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  type        = "zip"
  source_dir  = "${path.module}/../lambda/a2a_worker"
  output_path = "${path.module}/../lambda/a2a_worker/package.zip"
  excludes    = ["package.zip", "README.md", "__pycache__/*", "*.pyc"]
}

resource "aws_iam_role" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  name = "${local.name_prefix}-a2a-worker-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  name = "a2a-worker-permissions"
  role = aws_iam_role.a2a_worker[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "InvokeAgentRuntime"
        Effect = "Allow"
        Action = ["bedrock-agentcore:InvokeAgentRuntime"]
        Resource = [
          aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn,
          "${aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn}/*",
        ]
      },
      {
        Sid      = "TaskStore"
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.a2a_tasks[0].arn
      },
      {
        Sid      = "ConsumeQueue"
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.a2a_tasks[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  function_name    = "${local.name_prefix}-a2a-worker"
  description      = "Runs one A2A task to completion out of band (SQS-triggered)"
  role             = aws_iam_role.a2a_worker[0].arn
  handler          = "worker.lambda_handler"
  runtime          = "python3.13"
  timeout          = var.a2a_worker_timeout
  memory_size      = 512
  filename         = data.archive_file.a2a_worker[0].output_path
  source_code_hash = data.archive_file.a2a_worker[0].output_base64sha256

  environment {
    variables = {
      A2A_TASKS_TABLE         = aws_dynamodb_table.a2a_tasks[0].name
      AGENT_RUNTIME_ARN       = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn
      AGENT_RUNTIME_QUALIFIER = "DEFAULT"
      LOG_LEVEL               = var.log_level
    }
  }

  tags = { Component = "a2a" }
}

resource "aws_lambda_event_source_mapping" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  event_source_arn        = aws_sqs_queue.a2a_tasks[0].arn
  function_name           = aws_lambda_function.a2a_worker[0].arn
  batch_size              = 1
  function_response_types = ["ReportBatchItemFailures"]

  # Cap concurrent agent turns here rather than via reserved concurrency, so it
  # doesn't eat into the account's unreserved concurrency pool. Minimum is 2.
  scaling_config {
    maximum_concurrency = max(var.a2a_worker_max_concurrency, 2)
  }
}

resource "aws_cloudwatch_log_group" "a2a_worker" {
  count = local.a2a_enabled ? 1 : 0

  name              = "/aws/lambda/${aws_lambda_function.a2a_worker[0].function_name}"
  retention_in_days = 30

  tags = { Component = "a2a" }
}
