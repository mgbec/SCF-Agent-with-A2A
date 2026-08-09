################################################################################
# SCF Compliance Agent - Bedrock AgentCore Infrastructure
# Terraform AWS Provider ~> 6.56
################################################################################

terraform {
  required_version = ">= 1.6"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.56"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.0"
    }
    time = {
      source  = "hashicorp/time"
      version = "~> 0.12"
    }
  }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = var.project_name
      ManagedBy   = "terraform"
      Application = "scf-compliance-agent"
    }
  }
}

# --------------------------------------------------------------------------
# Data Sources
# --------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  account_id  = data.aws_caller_identity.current.account_id
  region      = data.aws_region.current.region
  name_prefix = var.project_name
}

# --------------------------------------------------------------------------
# S3 Bucket - SCF Knowledge Base Data
# --------------------------------------------------------------------------

resource "aws_s3_bucket" "scf_data" {
  bucket = "${local.name_prefix}-scf-data-${local.account_id}-${local.region}"
}

resource "aws_s3_bucket_versioning" "scf_data" {
  bucket = aws_s3_bucket.scf_data.id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "scf_data" {
  bucket = aws_s3_bucket.scf_data.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "scf_data" {
  bucket = aws_s3_bucket.scf_data.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# --------------------------------------------------------------------------
# ECR Repository - Agent Container
# --------------------------------------------------------------------------

resource "aws_ecr_repository" "agent" {
  name                 = "${local.name_prefix}-compliance-agent"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }
}

# --------------------------------------------------------------------------
# Bedrock Knowledge Base - SCF Controls
# --------------------------------------------------------------------------

resource "aws_iam_role" "knowledge_base" {
  name = "${local.name_prefix}-kb-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "bedrock.amazonaws.com"
        }
        Condition = {
          StringEquals = {
            "aws:SourceAccount" = local.account_id
          }
          ArnLike = {
            "aws:SourceArn" = "arn:aws:bedrock:${local.region}:${local.account_id}:knowledge-base/*"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "knowledge_base_s3" {
  name = "s3-access"
  role = aws_iam_role.knowledge_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.scf_data.arn,
          "${aws_s3_bucket.scf_data.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "knowledge_base_bedrock" {
  name = "bedrock-model-access"
  role = aws_iam_role.knowledge_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock:ListFoundationModels",
          "bedrock:ListCustomModels"
        ]
        Resource = "*"
      },
      {
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel"
        ]
        Resource = "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"
      }
    ]
  })
}

resource "aws_iam_role_policy" "knowledge_base_s3vectors" {
  name = "s3-vectors-access"
  role = aws_iam_role.knowledge_base.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "S3VectorsAccess"
        Effect = "Allow"
        Action = [
          "s3vectors:CreateIndex",
          "s3vectors:DeleteIndex",
          "s3vectors:GetIndex",
          "s3vectors:ListIndexes",
          "s3vectors:PutVectors",
          "s3vectors:GetVectors",
          "s3vectors:DeleteVectors",
          "s3vectors:QueryVectors",
          "s3vectors:ListVectorBuckets",
          "s3vectors:GetVectorBucket"
        ]
        Resource = [
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-scf-vectors",
          "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-scf-vectors/*"
        ]
      }
    ]
  })
}

# --------------------------------------------------------------------------
# S3 Vectors Bucket & Index (vector store for Knowledge Base)
# Note: aws_s3vectors_* resources don't exist in provider 6.56 yet, so we
# use local-exec provisioners with lifecycle destroy handlers.
# --------------------------------------------------------------------------

resource "terraform_data" "s3_vectors_bucket" {
  input = "${local.name_prefix}-scf-vectors"

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    command     = "aws s3vectors create-vector-bucket --vector-bucket-name '${local.name_prefix}-scf-vectors' --region '${local.region}' 2>&1 | Out-Null; Write-Host 'S3 Vectors bucket created'"
  }

  provisioner "local-exec" {
    when        = destroy
    interpreter = ["PowerShell", "-Command"]
    command     = "aws s3vectors delete-index --vector-bucket-name '${self.output}' --index-name 'scf-controls-index' --region us-east-1 2>&1 | Out-Null; aws s3vectors delete-vector-bucket --vector-bucket-name '${self.output}' --region us-east-1 2>&1 | Out-Null; Write-Host 'S3 Vectors bucket deleted'"
  }
}

resource "terraform_data" "s3_vectors_index" {
  depends_on = [terraform_data.s3_vectors_bucket]
  input      = "${local.name_prefix}-scf-vectors"

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    command     = "aws s3vectors create-index --vector-bucket-name '${local.name_prefix}-scf-vectors' --index-name 'scf-controls-index' --data-type float32 --dimension 1024 --distance-metric cosine --region '${local.region}' 2>&1 | Out-Null; Write-Host 'S3 Vectors index created'"
  }
}

# IAM role propagation delay
resource "time_sleep" "wait_for_kb_role" {
  depends_on = [
    aws_iam_role.knowledge_base,
    aws_iam_role_policy.knowledge_base_s3,
    aws_iam_role_policy.knowledge_base_bedrock,
    aws_iam_role_policy.knowledge_base_s3vectors,
    terraform_data.s3_vectors_index,
  ]
  create_duration = "15s"
}

resource "aws_bedrockagent_knowledge_base" "scf" {
  name     = "${local.name_prefix}-scf-knowledge-base"
  role_arn = aws_iam_role.knowledge_base.arn

  knowledge_base_configuration {
    type = "VECTOR"

    vector_knowledge_base_configuration {
      embedding_model_arn = "arn:aws:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"
    }
  }

  storage_configuration {
    type = "S3_VECTORS"

    s3_vectors_configuration {
      vector_bucket_arn = "arn:aws:s3vectors:${local.region}:${local.account_id}:bucket/${local.name_prefix}-scf-vectors"
      index_name        = "scf-controls-index"
    }
  }

  depends_on = [time_sleep.wait_for_kb_role]
}

resource "aws_bedrockagent_data_source" "scf_json" {
  name                 = "scf-controls-json"
  knowledge_base_id    = aws_bedrockagent_knowledge_base.scf.id
  data_deletion_policy = "RETAIN"

  data_source_configuration {
    type = "S3"

    s3_configuration {
      bucket_arn = aws_s3_bucket.scf_data.arn
    }
  }
}

# --------------------------------------------------------------------------
# AgentCore Memory - Compliance Assessment Sessions
# --------------------------------------------------------------------------

resource "aws_bedrockagentcore_memory" "compliance" {
  name                  = "${replace(local.name_prefix, "-", "_")}_compliance_memory"
  description           = "Stores compliance assessment sessions, maturity scores, and gap analysis history"
  event_expiry_duration = 90
}

# --------------------------------------------------------------------------
# IAM Role - AgentCore Runtime
# --------------------------------------------------------------------------

resource "aws_iam_role" "agentcore_runtime" {
  name = "${local.name_prefix}-agentcore-runtime-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_ecr" {
  name = "ecr-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["ecr:GetAuthorizationToken"]
        Resource = ["*"]
      },
      {
        Effect = "Allow"
        Action = [
          "ecr:BatchGetImage",
          "ecr:GetDownloadUrlForLayer"
        ]
        Resource = [aws_ecr_repository.agent.arn]
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_bedrock" {
  name = "bedrock-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ModelInvocation"
        Effect = "Allow"
        Action = [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream"
        ]
        Resource = [
          "arn:aws:bedrock:${local.region}:${local.account_id}:inference-profile/${var.bedrock_model_id}",
          "arn:aws:bedrock:*::foundation-model/anthropic.*"
        ]
      },
      {
        Sid    = "KnowledgeBaseRetrieval"
        Effect = "Allow"
        Action = [
          "bedrock:Retrieve"
        ]
        Resource = aws_bedrockagent_knowledge_base.scf.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_s3" {
  name = "s3-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "s3:GetObject",
          "s3:ListBucket"
        ]
        Resource = [
          aws_s3_bucket.scf_data.arn,
          "${aws_s3_bucket.scf_data.arn}/*"
        ]
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_memory" {
  name = "memory-access"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:GetMemory",
          "bedrock-agentcore:PutMemory",
          "bedrock-agentcore:SearchMemory"
        ]
        Resource = aws_bedrockagentcore_memory.compliance.arn
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_logs" {
  name = "cloudwatch-logs"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:log-group:/aws/bedrock-agentcore/runtimes/*"
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_gateway_invoke" {
  name = "gateway-invoke"
  role = aws_iam_role.agentcore_runtime.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeGateway"
        ]
        Resource = aws_bedrockagentcore_gateway.compliance.gateway_arn
      }
    ]
  })
}

# --------------------------------------------------------------------------
# AgentCore Runtime - Compliance Agent
# --------------------------------------------------------------------------

resource "aws_bedrockagentcore_agent_runtime" "compliance_agent" {
  agent_runtime_name = "${replace(local.name_prefix, "-", "_")}_compliance_agent"
  description        = "SCF 2026.2 Compliance Assessment Agent - provides control lookup, framework mapping, maturity assessment, and gap analysis"
  role_arn           = aws_iam_role.agentcore_runtime.arn

  agent_runtime_artifact {
    container_configuration {
      container_uri = "${aws_ecr_repository.agent.repository_url}:latest"
    }
  }

  environment_variables = {
    SCF_DATA_BUCKET   = aws_s3_bucket.scf_data.id
    KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.scf.id
    MEMORY_ID         = aws_bedrockagentcore_memory.compliance.id
    GATEWAY_ID        = aws_bedrockagentcore_gateway.compliance.gateway_id
    DYNAMODB_TABLE    = aws_dynamodb_table.scf_controls.name
    GUARDRAIL_ID      = aws_bedrock_guardrail.scf_agent.guardrail_id
    GUARDRAIL_VERSION = aws_bedrock_guardrail_version.scf_agent.version
    BEDROCK_MODEL_ID  = var.bedrock_model_id
    AWS_REGION        = local.region
    LOG_LEVEL         = var.log_level
  }

  network_configuration {
    network_mode = "PUBLIC"
  }

  lifecycle_configuration {
    idle_runtime_session_timeout = 300
  }

  protocol_configuration {
    server_protocol = "HTTP"
  }

  tags = {
    Component = "runtime"
  }
}

# --------------------------------------------------------------------------
# AgentCore Gateway - MCP-Compatible API Endpoint
# --------------------------------------------------------------------------

resource "aws_iam_role" "agentcore_gateway" {
  name = "${local.name_prefix}-agentcore-gateway-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = "sts:AssumeRole"
        Principal = {
          Service = "bedrock-agentcore.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "agentcore_gateway_websearch" {
  name = "web-search-connector"
  role = aws_iam_role.agentcore_gateway.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = [
          "bedrock-agentcore:InvokeConnector"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "bedrock-agentcore:ConnectorId" = "web-search"
          }
        }
      }
    ]
  })
}

resource "aws_bedrockagentcore_gateway" "compliance" {
  name     = "${local.name_prefix}-compliance-gateway"
  role_arn = aws_iam_role.agentcore_gateway.arn

  authorizer_type = "AWS_IAM"
  protocol_type   = "MCP"

  protocol_configuration {
    mcp {
      instructions       = "SCF Compliance Assessment Gateway - exposes web search and compliance agent tools via MCP"
      supported_versions = ["2025-03-26", "2025-06-18"]
    }
  }

  tags = {
    Component = "gateway"
  }
}

# Web Search Tool - managed connector target on the MCP Gateway
# Note: The connector target type is provisioned via CLI as the Terraform
# provider 6.56 does not yet have native connector block support for
# gateway targets. This will be importable when provider support lands.
resource "terraform_data" "web_search_target" {
  input = aws_bedrockagentcore_gateway.compliance.gateway_id

  provisioner "local-exec" {
    interpreter = ["PowerShell", "-Command"]
    command     = <<-EOT
      $config = '{"connector":{"source":{"connectorId":"web-search"}}}'
      $configFile = [System.IO.Path]::GetTempFileName()
      $config | Set-Content -Path $configFile -Encoding UTF8
      aws bedrock-agentcore-control create-gateway-target --gateway-identifier "${aws_bedrockagentcore_gateway.compliance.gateway_id}" --name "web-search" --target-configuration "file://$configFile" --region "${local.region}"
      Remove-Item $configFile -ErrorAction SilentlyContinue
    EOT
  }
}

# Agent Runtime target - routed via a separate non-MCP gateway for HTTP
resource "aws_bedrockagentcore_gateway" "agent_http" {
  name     = "${local.name_prefix}-agent-gateway"
  role_arn = aws_iam_role.agentcore_gateway.arn

  authorizer_type = "AWS_IAM"

  tags = {
    Component = "gateway"
  }
}

resource "aws_bedrockagentcore_gateway_target" "compliance_agent" {
  gateway_identifier = aws_bedrockagentcore_gateway.agent_http.gateway_id
  name               = "scf-compliance-agent"
  description        = "Routes requests to the SCF Compliance Assessment Agent runtime"

  target_configuration {
    http {
      agentcore_runtime {
        arn       = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn
        qualifier = "DEFAULT"
      }
    }
  }
}
