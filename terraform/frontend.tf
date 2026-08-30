################################################################################
# Streamlit frontend - ECS Fargate + ALB + CloudFront
#
# Streamlit needs a persistent WebSocket (/_stcore/stream); App Runner does not
# support WebSockets, so the frontend runs on Fargate behind an ALB, with
# CloudFront in front for a free HTTPS *.cloudfront.net domain (WebSocket-capable,
# no ACM cert / custom domain required).
#
#   Browser --HTTPS/WSS--> CloudFront --HTTP--> ALB --> Fargate task (Streamlit :8501)
#
# Direct ALB access is blocked: CloudFront injects a secret X-Origin-Verify
# header and the ALB listener 403s anything without it.
#
# Auth is the app-level OIDC gate in frontend/auth.py (Streamlit st.login), using
# a dedicated confidential Cognito client on the pool from cognito-a2a.tf.
#
# TWO-PHASE APPLY (CloudFront's domain is only known after creation, but the
# Cognito callback + the container's AUTH_REDIRECT_URI must contain it):
#   1. terraform apply          (frontend_base_url = "")   -> stack comes up
#   2. set frontend_base_url = <frontend_url output> in terraform.tfvars
#      terraform apply          -> login becomes functional
#
# BOOTSTRAP (image must exist before the ECS service):
#   terraform apply -target=aws_ecr_repository.frontend
#   ../frontend/build-and-push.ps1
#   terraform apply
################################################################################

locals {
  frontend_enabled  = var.enable_frontend
  frontend_base     = var.frontend_base_url != "" ? var.frontend_base_url : "http://localhost:8501"
  frontend_redirect = "${local.frontend_base}/oauth2callback"
  frontend_oidc_metadata_url = var.enable_a2a ? (
    "https://cognito-idp.${local.region}.amazonaws.com/${aws_cognito_user_pool.a2a[0].id}/.well-known/openid-configuration"
  ) : ""
  frontend_container_name = "frontend"
  frontend_port           = 8501
}

# --------------------------------------------------------------------------
# ECR repository for the frontend image
# --------------------------------------------------------------------------
resource "aws_ecr_repository" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name                 = "${local.name_prefix}-frontend"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = { Component = "frontend" }
}

# --------------------------------------------------------------------------
# Cognito app client for the frontend (confidential, authorization_code)
# --------------------------------------------------------------------------
resource "aws_cognito_user_pool_client" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name         = "${local.name_prefix}-frontend-web"
  user_pool_id = aws_cognito_user_pool.a2a[0].id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes                 = ["openid", "email", "profile"]
  supported_identity_providers         = ["COGNITO"]

  callback_urls = [local.frontend_redirect]
  logout_urls   = distinct([local.frontend_base, "${local.frontend_base}/"])

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  lifecycle {
    precondition {
      condition     = var.enable_a2a
      error_message = "enable_frontend requires enable_a2a: the frontend reuses the Cognito user pool defined in cognito-a2a.tf."
    }
  }

  depends_on = [aws_cognito_user_pool_domain.a2a]
}

# --------------------------------------------------------------------------
# Secrets: Cognito client secret + a Streamlit cookie secret + an origin token
# --------------------------------------------------------------------------
resource "random_password" "frontend_cookie_secret" {
  count   = local.frontend_enabled ? 1 : 0
  length  = 64
  special = false
}

resource "random_password" "frontend_origin_secret" {
  count   = local.frontend_enabled ? 1 : 0
  length  = 40
  special = false
}

resource "aws_ssm_parameter" "frontend_client_secret" {
  count = local.frontend_enabled ? 1 : 0

  name  = "/${local.name_prefix}/frontend/auth/client-secret"
  type  = "SecureString"
  value = aws_cognito_user_pool_client.frontend[0].client_secret

  tags = { Component = "frontend" }
}

resource "aws_ssm_parameter" "frontend_cookie_secret" {
  count = local.frontend_enabled ? 1 : 0

  name  = "/${local.name_prefix}/frontend/auth/cookie-secret"
  type  = "SecureString"
  value = random_password.frontend_cookie_secret[0].result

  tags = { Component = "frontend" }
}

# --------------------------------------------------------------------------
# Networking (default VPC)
# --------------------------------------------------------------------------
data "aws_vpc" "default" {
  count   = local.frontend_enabled ? 1 : 0
  default = true
}

data "aws_subnets" "default" {
  count = local.frontend_enabled ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }
}

data "aws_ec2_managed_prefix_list" "cloudfront" {
  count = local.frontend_enabled ? 1 : 0
  name  = "com.amazonaws.global.cloudfront.origin-facing"
}

resource "aws_security_group" "frontend_alb" {
  count = local.frontend_enabled ? 1 : 0

  name        = "${local.name_prefix}-frontend-alb"
  description = "SCF frontend ALB - inbound from CloudFront only"
  vpc_id      = data.aws_vpc.default[0].id

  ingress {
    description     = "HTTP from CloudFront edge"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    prefix_list_ids = [data.aws_ec2_managed_prefix_list.cloudfront[0].id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Component = "frontend" }
}

resource "aws_security_group" "frontend_task" {
  count = local.frontend_enabled ? 1 : 0

  name        = "${local.name_prefix}-frontend-task"
  description = "SCF frontend Fargate task - inbound from the ALB only"
  vpc_id      = data.aws_vpc.default[0].id

  ingress {
    description     = "Streamlit from the ALB"
    from_port       = local.frontend_port
    to_port         = local.frontend_port
    protocol        = "tcp"
    security_groups = [aws_security_group.frontend_alb[0].id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Component = "frontend" }
}

# --------------------------------------------------------------------------
# ALB
# --------------------------------------------------------------------------
resource "aws_lb" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name               = "${local.name_prefix}-frontend"
  load_balancer_type = "application"
  security_groups    = [aws_security_group.frontend_alb[0].id]
  subnets            = data.aws_subnets.default[0].ids
  idle_timeout       = 3600 # long-lived Streamlit WebSocket + slow agent calls

  tags = { Component = "frontend" }
}

resource "aws_lb_target_group" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name        = "${local.name_prefix}-frontend"
  port        = local.frontend_port
  protocol    = "HTTP"
  vpc_id      = data.aws_vpc.default[0].id
  target_type = "ip"

  deregistration_delay = 30

  health_check {
    path                = "/_stcore/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 5
  }

  tags = { Component = "frontend" }
}

resource "aws_lb_listener" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  load_balancer_arn = aws_lb.frontend[0].arn
  port              = 80
  protocol          = "HTTP"

  # Anything that didn't come through CloudFront (no shared secret header) is refused.
  default_action {
    type = "fixed-response"
    fixed_response {
      content_type = "text/plain"
      message_body = "Direct access is not allowed. Use the CloudFront URL."
      status_code  = "403"
    }
  }

  tags = { Component = "frontend" }
}

resource "aws_lb_listener_rule" "frontend_from_cloudfront" {
  count = local.frontend_enabled ? 1 : 0

  listener_arn = aws_lb_listener.frontend[0].arn
  priority     = 1

  action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.frontend[0].arn
  }

  condition {
    http_header {
      http_header_name = "X-Origin-Verify"
      values           = [random_password.frontend_origin_secret[0].result]
    }
  }
}

# --------------------------------------------------------------------------
# IAM - ECS task execution role (pulls image + secrets) and task role (app perms)
# --------------------------------------------------------------------------
resource "aws_iam_role" "frontend_task_exec" {
  count = local.frontend_enabled ? 1 : 0

  name = "${local.name_prefix}-frontend-task-exec-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "frontend_task_exec_managed" {
  count = local.frontend_enabled ? 1 : 0

  role       = aws_iam_role.frontend_task_exec[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role_policy" "frontend_task_exec_secrets" {
  count = local.frontend_enabled ? 1 : 0

  name = "read-auth-secrets"
  role = aws_iam_role.frontend_task_exec[0].id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect = "Allow"
        Action = ["ssm:GetParameters"]
        Resource = [
          aws_ssm_parameter.frontend_client_secret[0].arn,
          aws_ssm_parameter.frontend_cookie_secret[0].arn,
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["kms:Decrypt"]
        Resource = "*"
        Condition = {
          StringEquals = { "kms:ViaService" = "ssm.${local.region}.amazonaws.com" }
        }
      },
    ]
  })
}

resource "aws_iam_role" "frontend_task" {
  count = local.frontend_enabled ? 1 : 0

  name = "${local.name_prefix}-frontend-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "frontend_task" {
  count = local.frontend_enabled ? 1 : 0

  name = "frontend-permissions"
  role = aws_iam_role.frontend_task[0].id

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
        Sid    = "ApprovedAnswersReadWrite"
        Effect = "Allow"
        Action = [
          "dynamodb:GetItem",
          "dynamodb:Query",
          "dynamodb:Scan",
          "dynamodb:PutItem",
          "dynamodb:UpdateItem",
          "dynamodb:DeleteItem",
        ]
        Resource = [
          aws_dynamodb_table.approved_answers.arn,
          "${aws_dynamodb_table.approved_answers.arn}/index/*",
        ]
      },
    ]
  })
}

# --------------------------------------------------------------------------
# ECS Fargate service
# --------------------------------------------------------------------------
resource "aws_ecs_cluster" "frontend" {
  count = local.frontend_enabled ? 1 : 0
  name  = "${local.name_prefix}-frontend"

  tags = { Component = "frontend" }
}

resource "aws_cloudwatch_log_group" "frontend" {
  count             = local.frontend_enabled ? 1 : 0
  name              = "/ecs/${local.name_prefix}-frontend"
  retention_in_days = 30

  tags = { Component = "frontend" }
}

resource "aws_ecs_task_definition" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  family                   = "${local.name_prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.frontend_task_exec[0].arn
  task_role_arn            = aws_iam_role.frontend_task[0].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "X86_64"
  }

  container_definitions = jsonencode([
    {
      name      = local.frontend_container_name
      image     = "${aws_ecr_repository.frontend[0].repository_url}:latest"
      essential = true
      portMappings = [{
        containerPort = local.frontend_port
        protocol      = "tcp"
      }]
      environment = [
        { name = "AWS_REGION", value = local.region },
        { name = "SCF_AGENT_ARN", value = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn },
        { name = "AUTH_CLIENT_ID", value = aws_cognito_user_pool_client.frontend[0].id },
        { name = "AUTH_SERVER_METADATA_URL", value = local.frontend_oidc_metadata_url },
        { name = "AUTH_REDIRECT_URI", value = local.frontend_redirect },
      ]
      secrets = [
        { name = "AUTH_CLIENT_SECRET", valueFrom = aws_ssm_parameter.frontend_client_secret[0].arn },
        { name = "AUTH_COOKIE_SECRET", valueFrom = aws_ssm_parameter.frontend_cookie_secret[0].arn },
      ]
      logConfiguration = {
        logDriver = "awslogs"
        options = {
          "awslogs-group"         = aws_cloudwatch_log_group.frontend[0].name
          "awslogs-region"        = local.region
          "awslogs-stream-prefix" = "frontend"
        }
      }
    }
  ])

  tags = { Component = "frontend" }
}

resource "aws_ecs_service" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  name            = "${local.name_prefix}-frontend"
  cluster         = aws_ecs_cluster.frontend[0].id
  task_definition = aws_ecs_task_definition.frontend[0].arn
  desired_count   = 1
  launch_type     = "FARGATE"

  health_check_grace_period_seconds = 120

  network_configuration {
    subnets          = data.aws_subnets.default[0].ids
    security_groups  = [aws_security_group.frontend_task[0].id]
    assign_public_ip = true
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend[0].arn
    container_name   = local.frontend_container_name
    container_port   = local.frontend_port
  }

  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  depends_on = [aws_lb_listener.frontend]

  tags = { Component = "frontend" }
}

# --------------------------------------------------------------------------
# CloudFront - free HTTPS *.cloudfront.net, WebSocket-capable
# --------------------------------------------------------------------------
data "aws_cloudfront_cache_policy" "disabled" {
  count = local.frontend_enabled ? 1 : 0
  name  = "Managed-CachingDisabled"
}

data "aws_cloudfront_origin_request_policy" "all_viewer" {
  count = local.frontend_enabled ? 1 : 0
  name  = "Managed-AllViewer"
}

resource "aws_cloudfront_distribution" "frontend" {
  count = local.frontend_enabled ? 1 : 0

  enabled         = true
  comment         = "SCF Compliance Agent frontend"
  price_class     = "PriceClass_100"
  is_ipv6_enabled = true

  origin {
    domain_name = aws_lb.frontend[0].dns_name
    origin_id   = "alb"

    custom_origin_config {
      http_port                = 80
      https_port               = 443
      origin_protocol_policy   = "http-only"
      origin_ssl_protocols     = ["TLSv1.2"]
      origin_read_timeout      = 60
      origin_keepalive_timeout = 60
    }

    custom_header {
      name  = "X-Origin-Verify"
      value = random_password.frontend_origin_secret[0].result
    }
  }

  default_cache_behavior {
    target_origin_id         = "alb"
    viewer_protocol_policy   = "redirect-to-https"
    allowed_methods          = ["GET", "HEAD", "OPTIONS", "PUT", "POST", "PATCH", "DELETE"]
    cached_methods           = ["GET", "HEAD"]
    compress                 = true
    cache_policy_id          = data.aws_cloudfront_cache_policy.disabled[0].id
    origin_request_policy_id = data.aws_cloudfront_origin_request_policy.all_viewer[0].id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = true
  }

  tags = { Component = "frontend" }
}
