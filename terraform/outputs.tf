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

output "agent_code_s3_key" {
  description = "S3 key for the agent code deployment package"
  value       = aws_s3_object.agent_code.key
}

output "memory_id" {
  description = "ID of the AgentCore memory for compliance sessions"
  value       = aws_bedrockagentcore_memory.compliance.id
}
