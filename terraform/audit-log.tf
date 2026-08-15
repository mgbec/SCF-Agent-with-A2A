################################################################################
# Audit Log - Tracks all changes to approved answers
#
# DynamoDB Streams captures every INSERT, MODIFY, DELETE on the answers table.
# A Lambda writes each change to an audit log table with before/after values.
################################################################################

# Enable streams on the approved answers table
resource "aws_dynamodb_table" "answer_audit_log" {
  name         = "${local.name_prefix}-answer-audit-log"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "audit_id"

  attribute {
    name = "audit_id"
    type = "S"
  }

  attribute {
    name = "answer_id"
    type = "S"
  }

  attribute {
    name = "timestamp"
    type = "S"
  }

  global_secondary_index {
    name            = "answer-history-index"
    hash_key        = "answer_id"
    range_key       = "timestamp"
    projection_type = "ALL"
  }

  tags = {
    Component = "audit-log"
  }
}

# Lambda to process DynamoDB Stream events
data "archive_file" "audit_logger" {
  type        = "zip"
  source_file = "${path.module}/../lambda/audit_logger/handler.py"
  output_path = "${path.module}/../lambda/audit_logger/package.zip"
}

resource "aws_iam_role" "audit_logger" {
  name = "${local.name_prefix}-audit-logger-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "audit_logger" {
  name = "audit-logger-permissions"
  role = aws_iam_role.audit_logger.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:PutItem"
        ]
        Resource = aws_dynamodb_table.answer_audit_log.arn
      },
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetRecords",
          "dynamodb:GetShardIterator",
          "dynamodb:DescribeStream",
          "dynamodb:ListStreams"
        ]
        Resource = "${aws_dynamodb_table.approved_answers.arn}/stream/*"
      },
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      }
    ]
  })
}

resource "aws_lambda_function" "audit_logger" {
  function_name    = "${local.name_prefix}-audit-logger"
  description      = "Captures all changes to approved answers into an audit log"
  role             = aws_iam_role.audit_logger.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  timeout          = 60
  memory_size      = 256
  filename         = data.archive_file.audit_logger.output_path
  source_code_hash = data.archive_file.audit_logger.output_base64sha256

  environment {
    variables = {
      AUDIT_TABLE = aws_dynamodb_table.answer_audit_log.name
    }
  }

  tags = {
    Component = "audit-log"
  }
}

# Connect DynamoDB Stream to Lambda
resource "aws_lambda_event_source_mapping" "audit_stream" {
  event_source_arn  = aws_dynamodb_table.approved_answers.stream_arn
  function_name     = aws_lambda_function.audit_logger.arn
  starting_position = "LATEST"
  batch_size        = 10

  depends_on = [aws_iam_role_policy.audit_logger]
}

resource "aws_cloudwatch_log_group" "audit_logger" {
  name              = "/aws/lambda/${aws_lambda_function.audit_logger.function_name}"
  retention_in_days = 365

  tags = {
    Component = "audit-log"
  }
}
