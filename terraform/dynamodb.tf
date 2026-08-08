################################################################################
# DynamoDB - Full SCF Control Data (no size limits)
#
# Used for detail retrieval after KB search identifies relevant controls.
# Each item contains the complete control with all maturity criteria,
# all framework mappings, and full solution text.
################################################################################

resource "aws_dynamodb_table" "scf_controls" {
  name         = "${local.name_prefix}-scf-controls"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "scf_id"

  attribute {
    name = "scf_id"
    type = "S"
  }

  attribute {
    name = "domain_id"
    type = "S"
  }

  global_secondary_index {
    name            = "domain-index"
    hash_key        = "domain_id"
    projection_type = "ALL"
  }

  tags = {
    Component = "scf-data"
  }
}

# IAM policy for the agent runtime to read DynamoDB
resource "aws_iam_role_policy" "agentcore_dynamodb" {
  name = "dynamodb-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:BatchGetItem"
        ]
        Resource = [
          aws_dynamodb_table.scf_controls.arn,
          "${aws_dynamodb_table.scf_controls.arn}/index/*"
        ]
      }
    ]
  })
}
