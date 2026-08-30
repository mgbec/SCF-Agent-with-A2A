################################################################################
# Outputs
################################################################################

output "agent_runtime_arn" {
  description = "ARN of the deployed AgentCore compliance agent runtime"
  value       = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_arn
}

output "agent_runtime_id" {
  description = "ID of the AgentCore agent runtime"
  value       = aws_bedrockagentcore_agent_runtime.compliance_agent.agent_runtime_id
}

output "gateway_arn" {
  description = "ARN of the MCP Gateway (Web Search + tools)"
  value       = aws_bedrockagentcore_gateway.compliance.gateway_arn
}

output "gateway_id" {
  description = "ID of the MCP AgentCore gateway"
  value       = aws_bedrockagentcore_gateway.compliance.gateway_id
}

output "gateway_url" {
  description = "MCP Gateway URL endpoint"
  value       = aws_bedrockagentcore_gateway.compliance.gateway_url
}

output "agent_gateway_url" {
  description = "HTTP Gateway URL for direct agent invocation"
  value       = aws_bedrockagentcore_gateway.agent_http.gateway_url
}

output "knowledge_base_id" {
  description = "ID of the Bedrock Knowledge Base containing SCF data"
  value       = aws_bedrockagent_knowledge_base.scf.id
}

output "scf_data_bucket" {
  description = "S3 bucket name for SCF data"
  value       = aws_s3_bucket.scf_data.id
}

output "ecr_repository_url" {
  description = "ECR repository URL for the agent container image"
  value       = aws_ecr_repository.agent.repository_url
}

output "memory_id" {
  description = "ID of the AgentCore memory for compliance sessions"
  value       = aws_bedrockagentcore_memory.compliance.id
}

output "dynamodb_table_name" {
  description = "DynamoDB table name for full SCF control data"
  value       = aws_dynamodb_table.scf_controls.name
}

output "guardrail_id" {
  description = "Bedrock Guardrail ID"
  value       = aws_bedrock_guardrail.scf_agent.guardrail_id
}

output "guardrail_version" {
  description = "Bedrock Guardrail version applied by the agent runtime"
  value       = aws_bedrock_guardrail_version.scf_agent.version
}

output "deploy_operator_policy_arn" {
  description = "Attach this managed policy to the IAM user/role that runs the deploy scripts (build-and-push.ps1 / update-runtime.ps1)"
  value       = aws_iam_policy.deploy_operator.arn
}

################################################################################
# A2A (Agent-to-Agent) ingress
################################################################################

output "a2a_api_endpoint" {
  description = "Base URL of the A2A HTTP API"
  value       = local.a2a_enabled ? local.a2a_base_url : null
}

output "a2a_cognito_rpc_url" {
  description = "A2A JSON-RPC endpoint guarded by the Cognito authorizer (also handles message/stream)"
  value       = local.a2a_enabled ? "${local.a2a_base_url}/cognito/rpc" : null
}

output "a2a_cognito_agent_card_url" {
  description = "Public A2A Agent Card for the Cognito route"
  value       = local.a2a_enabled ? "${local.a2a_base_url}/cognito/.well-known/agent-card.json" : null
}

output "a2a_entra_rpc_url" {
  description = "A2A JSON-RPC endpoint guarded by the Entra ID authorizer"
  value       = local.a2a_entra ? "${local.a2a_base_url}/entra/rpc" : null
}

output "a2a_entra_agent_card_url" {
  description = "Public A2A Agent Card for the Entra ID route"
  value       = local.a2a_entra ? "${local.a2a_base_url}/entra/.well-known/agent-card.json" : null
}

output "a2a_generic_agent_card_url" {
  description = "Public A2A Agent Card listing both auth schemes"
  value       = local.a2a_enabled ? "${local.a2a_base_url}/.well-known/agent-card.json" : null
}

output "cognito_user_pool_id" {
  description = "Cognito user pool ID backing the A2A Cognito route"
  value       = local.a2a_enabled ? aws_cognito_user_pool.a2a[0].id : null
}

output "cognito_a2a_token_endpoint" {
  description = "Cognito OAuth2 token endpoint (client_credentials + authorization_code)"
  value       = local.a2a_enabled ? "${local.cognito_a2a_domain_base}/oauth2/token" : null
}

output "cognito_a2a_scope" {
  description = "Custom OAuth2 scope required to invoke the agent via the Cognito route"
  value       = local.a2a_enabled ? "${aws_cognito_resource_server.a2a[0].identifier}/invoke" : null
}

output "cognito_a2a_m2m_client_id" {
  description = "Client ID of the machine-to-machine (client_credentials) Cognito app client"
  value       = local.a2a_enabled ? aws_cognito_user_pool_client.a2a_m2m[0].id : null
}

output "cognito_a2a_m2m_client_secret" {
  description = "Client secret of the machine-to-machine Cognito app client"
  value       = local.a2a_enabled ? aws_cognito_user_pool_client.a2a_m2m[0].client_secret : null
  sensitive   = true
}

output "cognito_a2a_web_client_id" {
  description = "Client ID of the interactive (authorization_code / hosted UI) Cognito app client"
  value       = local.a2a_enabled ? aws_cognito_user_pool_client.a2a_web[0].id : null
}

################################################################################
# Streamlit frontend (App Runner)
################################################################################

output "frontend_url" {
  description = "Public HTTPS URL of the hosted Streamlit frontend (CloudFront)"
  value       = local.frontend_enabled ? "https://${aws_cloudfront_distribution.frontend[0].domain_name}" : null
}

output "frontend_ecr_repository_url" {
  description = "ECR repository URL for the frontend container image"
  value       = local.frontend_enabled ? aws_ecr_repository.frontend[0].repository_url : null
}

output "frontend_cognito_client_id" {
  description = "Cognito app client ID used by the frontend's OIDC login"
  value       = local.frontend_enabled ? aws_cognito_user_pool_client.frontend[0].id : null
}
