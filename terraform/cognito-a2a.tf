################################################################################
# Cognito user pool for the A2A (Agent-to-Agent) ingress
#
# One route of the A2A HTTP API is guarded by a Cognito JWT authorizer. This
# pool serves BOTH:
#   * machine-to-machine callers  -> client_credentials grant  (a2a_m2m client)
#   * interactive human users      -> authorization_code + hosted UI (a2a_web client)
#
# NOTE: Cognito client_credentials access tokens have no `aud` claim; they carry
# `client_id` + `scope`. The API Gateway HTTP API JWT authorizer matches the
# configured audience list against `aud` OR `client_id`, so we list BOTH client
# IDs as audiences (see terraform/a2a.tf) and both flows validate.
################################################################################

locals {
  cognito_a2a_domain_base = var.enable_a2a ? "https://${var.cognito_a2a_domain_prefix}.auth.${local.region}.amazoncognito.com" : ""
}

resource "aws_cognito_user_pool" "a2a" {
  count = var.enable_a2a ? 1 : 0

  name = "${local.name_prefix}-a2a"

  username_attributes      = ["email"]
  auto_verified_attributes = ["email"]

  admin_create_user_config {
    allow_admin_create_user_only = true
  }

  tags = {
    Component = "a2a"
  }
}

resource "aws_cognito_user_pool_domain" "a2a" {
  count = var.enable_a2a ? 1 : 0

  domain       = var.cognito_a2a_domain_prefix
  user_pool_id = aws_cognito_user_pool.a2a[0].id
}

resource "aws_cognito_resource_server" "a2a" {
  count = var.enable_a2a ? 1 : 0

  identifier   = "https://${local.name_prefix}-a2a"
  name         = "${local.name_prefix}-a2a"
  user_pool_id = aws_cognito_user_pool.a2a[0].id

  scope {
    scope_name        = "invoke"
    scope_description = "Invoke the SCF Compliance Assessment Agent via A2A"
  }
}

# Machine-to-machine client (agents / services): client_credentials grant
resource "aws_cognito_user_pool_client" "a2a_m2m" {
  count = var.enable_a2a ? 1 : 0

  name         = "${local.name_prefix}-a2a-m2m"
  user_pool_id = aws_cognito_user_pool.a2a[0].id

  generate_secret                      = true
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["client_credentials"]
  allowed_oauth_scopes                 = ["${aws_cognito_resource_server.a2a[0].identifier}/invoke"]

  access_token_validity = 60
  token_validity_units {
    access_token = "minutes"
  }

  depends_on = [aws_cognito_resource_server.a2a]
}

# Interactive human client: authorization_code flow via the hosted UI
resource "aws_cognito_user_pool_client" "a2a_web" {
  count = var.enable_a2a ? 1 : 0

  name         = "${local.name_prefix}-a2a-web"
  user_pool_id = aws_cognito_user_pool.a2a[0].id

  generate_secret                      = false
  allowed_oauth_flows_user_pool_client = true
  allowed_oauth_flows                  = ["code"]
  allowed_oauth_scopes = [
    "openid",
    "email",
    "${aws_cognito_resource_server.a2a[0].identifier}/invoke",
  ]
  callback_urls                = var.cognito_a2a_web_callback_urls
  logout_urls                  = var.cognito_a2a_web_callback_urls
  supported_identity_providers = ["COGNITO"]

  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  depends_on = [aws_cognito_resource_server.a2a]
}
