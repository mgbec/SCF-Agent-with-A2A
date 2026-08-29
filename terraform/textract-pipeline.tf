################################################################################
# Textract Document Ingestion Pipeline
#
# Triggered when documents are uploaded to the questionnaire S3 bucket.
# Extracts Q&A pairs via OCR and stores as draft answers.
################################################################################

data "archive_file" "textract_pipeline" {
  type        = "zip"
  source_file = "${path.module}/../lambda/textract_pipeline/handler.py"
  output_path = "${path.module}/../lambda/textract_pipeline/package.zip"
}

resource "aws_lambda_function" "textract_pipeline" {
  function_name    = "${local.name_prefix}-textract-pipeline"
  description      = "Extracts Q&A pairs from uploaded questionnaire documents via Textract OCR"
  role             = aws_iam_role.textract_pipeline.arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  timeout          = 900 # 15 minutes (Textract can be slow on large PDFs)
  memory_size      = 1024
  filename         = data.archive_file.textract_pipeline.output_path
  source_code_hash = data.archive_file.textract_pipeline.output_base64sha256

  environment {
    variables = {
      ANSWERS_TABLE  = aws_dynamodb_table.approved_answers.name
      UPLOADS_BUCKET = aws_s3_bucket.questionnaire_uploads.id
      SNS_TOPIC_ARN  = aws_sns_topic.scf_updates.arn
    }
  }

  tags = {
    Component = "textract-pipeline"
  }
}

# S3 event notification → EventBridge → Lambda
resource "aws_s3_bucket_notification" "questionnaire_uploads" {
  bucket      = aws_s3_bucket.questionnaire_uploads.id
  eventbridge = true
}

resource "aws_cloudwatch_event_rule" "document_upload" {
  name        = "${local.name_prefix}-document-upload"
  description = "Triggers Textract pipeline when documents are uploaded"

  event_pattern = jsonencode({
    source      = ["aws.s3"]
    detail-type = ["Object Created"]
    detail = {
      bucket = { name = [aws_s3_bucket.questionnaire_uploads.id] }
      object = {
        key = [{ suffix = ".pdf" }, { suffix = ".png" }, { suffix = ".jpg" }, { suffix = ".jpeg" }, { suffix = ".tiff" }]
      }
    }
  })

  tags = {
    Component = "textract-pipeline"
  }
}

resource "aws_cloudwatch_event_target" "textract_lambda" {
  rule = aws_cloudwatch_event_rule.document_upload.name
  arn  = aws_lambda_function.textract_pipeline.arn
}

resource "aws_lambda_permission" "eventbridge_textract" {
  statement_id  = "AllowEventBridgeInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.textract_pipeline.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.document_upload.arn
}

resource "aws_cloudwatch_log_group" "textract_pipeline" {
  name              = "/aws/lambda/${aws_lambda_function.textract_pipeline.function_name}"
  retention_in_days = 30

  tags = {
    Component = "textract-pipeline"
  }
}
