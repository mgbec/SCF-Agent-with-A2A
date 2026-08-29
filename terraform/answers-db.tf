################################################################################
# Approved Answers Database
#
# Stores historical questionnaire answers, assessment responses, and
# compliance documentation that the agent can reference and reuse.
################################################################################

resource "aws_dynamodb_table" "approved_answers" {
  name         = "${local.name_prefix}-approved-answers"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "answer_id"

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  attribute {
    name = "answer_id"
    type = "S"
  }

  attribute {
    name = "category"
    type = "S"
  }

  attribute {
    name = "source_framework"
    type = "S"
  }

  global_secondary_index {
    name            = "category-index"
    hash_key        = "category"
    projection_type = "ALL"
  }

  global_secondary_index {
    name            = "framework-index"
    hash_key        = "source_framework"
    projection_type = "ALL"
  }

  tags = {
    Component = "answers-database"
  }
}

# S3 bucket for uploaded questionnaire documents (PDFs, XLSX, DOCX)
resource "aws_s3_bucket" "questionnaire_uploads" {
  bucket = "${local.name_prefix}-questionnaire-uploads-${local.account_id}-${local.region}"
}

resource "aws_s3_bucket_versioning" "questionnaire_uploads" {
  bucket = aws_s3_bucket.questionnaire_uploads.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "questionnaire_uploads" {
  bucket = aws_s3_bucket.questionnaire_uploads.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "aws:kms" }
  }
}

resource "aws_s3_bucket_public_access_block" "questionnaire_uploads" {
  bucket                  = aws_s3_bucket.questionnaire_uploads.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# IAM: Agent runtime can read answers
resource "aws_iam_role_policy" "agentcore_answers_db" {
  name = "answers-db-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:BatchGetItem"
        ]
        Resource = [
          aws_dynamodb_table.approved_answers.arn,
          "${aws_dynamodb_table.approved_answers.arn}/index/*"
        ]
      }
    ]
  })
}

# IAM: Textract pipeline (for future OCR ingestion)
resource "aws_iam_role" "textract_pipeline" {
  name = "${local.name_prefix}-textract-pipeline-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "textract_pipeline" {
  name = "textract-pipeline-permissions"
  role = aws_iam_role.textract_pipeline.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["textract:StartDocumentAnalysis", "textract:GetDocumentAnalysis", "textract:DetectDocumentText"]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = ["s3:GetObject", "s3:ListBucket"]
        Resource = [
          aws_s3_bucket.questionnaire_uploads.arn,
          "${aws_s3_bucket.questionnaire_uploads.arn}/*"
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:UpdateItem"]
        Resource = aws_dynamodb_table.approved_answers.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      }
    ]
  })
}
