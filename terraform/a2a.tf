################################################################################
# A2A (Agent-to-Agent) ingress
#
# API Gateway HTTP API in front of a small "bridge" Lambda that translates the
# A2A protocol (JSON-RPC 2.0 + Agent Card discovery) into calls against the
# existing AgentCore Runtime (aws_bedrockagentcore_agent_runtime.compliance_agent
# in main.tf). Two routes, each with its own native JWT authorizer:
#
#   POST /cognito/rpc                          -> Cognito authorizer
#   GET  /cognito/.well-known/agent-card.json    (public)
#   POST /entra/rpc                            -> Entra ID authorizer (only when
#   GET  /entra/.well-known/agent-card.json       var.entra_tenant_id is set)
#   GET  /.well-known/agent-card.json            (public, generic card)
#
# Additive only: the AgentCore Runtime and its IAM / MCP / HTTP gateways are
# untouched.
################################################################################

locals {
  a2a_enabled   = var.enable_a2a
  a2a_entra     = var.enable_a2a && var.entra_tenant_id != ""
  a2a_base_url  = var.a2a_custom_domain != "" ? "https://${var.a2a_custom_domain}" : (var.enable_a2a ? aws_apigatewayv2_api.a2a[0].api_endpoint : "")
  a2a_entra_iss = var.entra_issuer_override != "" ? var.entra_issuer_override : "https://login.microsoftonline.com/${var.entra_tenant_id}/v2.0"
}

# --------------------------------------------------------------------------
# Task store - completed A2A tasks, TTL'd (supports tasks/get + tasks/resubscribe)
# --------------------------------------------------------------------------
resource "aws_dynamodb_table" "a2a_tasks" {
  count = local.a2a_enabled ? 1 : 0

  name         = "${local.name_prefix}-a2a-tasks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "task_id"

  attribute {
    name = "task_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Component = "a2a"
  }
}

# --------------------------------------------------------------------------
# Bridge Lambda
# --------------------------------------------------------------------------
data "archive_file" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  type        = "zip"
  source_dir  = "${path.module}/../lambda/a2a_bridge"
  output_path = "${path.module}/../lambda/a2a_bridge/package.zip"
  excludes    = ["package.zip", "README.md", "__pycache__/*", "*.pyc"]
}

resource "aws_iam_role" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  name = "${local.name_prefix}-a2a-bridge-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  name = "a2a-bridge-permissions"
  role = aws_iam_role.a2a_bridge[0].id

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
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.a2a_tasks[0].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:${local.region}:${local.account_id}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  function_name    = "${local.name_prefix}-a2a-bridge"
  description      = "Terminates incoming A2A protocol traffic and forwards it to the AgentCore Runtime"
  role             = aws_iam_role.a2a_bridge[0].arn
  handler          = "handler.lambda_handler"
  runtime          = "python3.13"
  timeout          = 120
  memory_size      = 512
  filename         = data.archive_file.a2a_bridge[0].output_path
  source_code_hash = data.archive_file.a2a_bridge[0].output_base64sha256

  environment {
    variables = {
      AGENT_RUNTIME_ARN       = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn
      AGENT_RUNTIME_QUALIFIER = "DEFAULT"
      A2A_TASKS_TABLE         = aws_dynamodb_table.a2a_tasks[0].name
      PUBLIC_BASE_URL         = local.a2a_base_url
      AGENT_NAME              = var.agent_public_name
      AGENT_VERSION           = "2026.2"
      COGNITO_TOKEN_URL       = "${local.cognito_a2a_domain_base}/oauth2/token"
      COGNITO_AUTHORIZE_URL   = "${local.cognito_a2a_domain_base}/oauth2/authorize"
      COGNITO_SCOPE           = "${aws_cognito_resource_server.a2a[0].identifier}/invoke"
      ENTRA_TENANT_ID         = var.entra_tenant_id
      LOG_LEVEL               = var.log_level
    }
  }

  tags = {
    Component = "a2a"
  }
}

resource "aws_cloudwatch_log_group" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  name              = "/aws/lambda/${aws_lambda_function.a2a_bridge[0].function_name}"
  retention_in_days = 30

  tags = {
    Component = "a2a"
  }
}

# --------------------------------------------------------------------------
# HTTP API + stage + access logs
# --------------------------------------------------------------------------
resource "aws_apigatewayv2_api" "a2a" {
  count = local.a2a_enabled ? 1 : 0

  name          = "${local.name_prefix}-a2a"
  protocol_type = "HTTP"
  description   = "A2A (Agent-to-Agent) ingress for the SCF Compliance Agent"

  cors_configuration {
    allow_origins = ["*"]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
    max_age       = 3600
  }

  tags = {
    Component = "a2a"
  }
}

resource "aws_cloudwatch_log_group" "a2a_api" {
  count = local.a2a_enabled ? 1 : 0

  name              = "/aws/apigateway/${local.name_prefix}-a2a"
  retention_in_days = 30

  tags = {
    Component = "a2a"
  }
}

resource "aws_apigatewayv2_stage" "a2a" {
  count = local.a2a_enabled ? 1 : 0

  api_id      = aws_apigatewayv2_api.a2a[0].id
  name        = "$default"
  auto_deploy = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.a2a_api[0].arn
    format = jsonencode({
      requestId      = "$context.requestId"
      httpMethod     = "$context.httpMethod"
      routeKey       = "$context.routeKey"
      path           = "$context.path"
      status         = "$context.status"
      responseLength = "$context.responseLength"
      authError      = "$context.authorizer.error"
      integrationErr = "$context.integration.error"
    })
  }

  tags = {
    Component = "a2a"
  }
}

# --------------------------------------------------------------------------
# JWT authorizers
# --------------------------------------------------------------------------
resource "aws_apigatewayv2_authorizer" "a2a_cognito" {
  count = local.a2a_enabled ? 1 : 0

  api_id           = aws_apigatewayv2_api.a2a[0].id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "cognito"

  jwt_configuration {
    # M2M (client_credentials) tokens have no `aud` - API Gateway falls back to
    # matching `client_id`, so both client IDs are listed here.
    audience = [
      aws_cognito_user_pool_client.a2a_m2m[0].id,
      aws_cognito_user_pool_client.a2a_web[0].id,
    ]
    issuer = "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.a2a[0].id}"
  }
}

resource "aws_apigatewayv2_authorizer" "a2a_entra" {
  count = local.a2a_entra ? 1 : 0

  api_id           = aws_apigatewayv2_api.a2a[0].id
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]
  name             = "entra"

  jwt_configuration {
    audience = [var.entra_audience]
    issuer   = local.a2a_entra_iss
  }
}

# --------------------------------------------------------------------------
# Integration + routes
# --------------------------------------------------------------------------
resource "aws_apigatewayv2_integration" "a2a_bridge" {
  count = local.a2a_enabled ? 1 : 0

  api_id                 = aws_apigatewayv2_api.a2a[0].id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.a2a_bridge[0].invoke_arn
  payload_format_version = "2.0"
}

locals {
  a2a_integration = local.a2a_enabled ? "integrations/${aws_apigatewayv2_integration.a2a_bridge[0].id}" : ""
}

# --- Cognito route ---------------------------------------------------------
resource "aws_apigatewayv2_route" "a2a_cognito_rpc" {
  count = local.a2a_enabled ? 1 : 0

  api_id             = aws_apigatewayv2_api.a2a[0].id
  route_key          = "POST /cognito/rpc"
  target             = local.a2a_integration
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.a2a_cognito[0].id
}

resource "aws_apigatewayv2_route" "a2a_cognito_card" {
  count = local.a2a_enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.a2a[0].id
  route_key = "GET /cognito/.well-known/agent-card.json"
  target    = local.a2a_integration
}

# --- Entra route (conditional) ------------------------------------------------
resource "aws_apigatewayv2_route" "a2a_entra_rpc" {
  count = local.a2a_entra ? 1 : 0

  api_id             = aws_apigatewayv2_api.a2a[0].id
  route_key          = "POST /entra/rpc"
  target             = local.a2a_integration
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.a2a_entra[0].id
}

resource "aws_apigatewayv2_route" "a2a_entra_card" {
  count = local.a2a_entra ? 1 : 0

  api_id    = aws_apigatewayv2_api.a2a[0].id
  route_key = "GET /entra/.well-known/agent-card.json"
  target    = local.a2a_integration
}

# --- Generic discovery card -------------------------------------------------
resource "aws_apigatewayv2_route" "a2a_generic_card" {
  count = local.a2a_enabled ? 1 : 0

  api_id    = aws_apigatewayv2_api.a2a[0].id
  route_key = "GET /.well-known/agent-card.json"
  target    = local.a2a_integration
}

resource "aws_lambda_permission" "a2a_bridge_apigw" {
  count = local.a2a_enabled ? 1 : 0

  statement_id  = "AllowA2AApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.a2a_bridge[0].function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.a2a[0].execution_arn}/*/*"
}
