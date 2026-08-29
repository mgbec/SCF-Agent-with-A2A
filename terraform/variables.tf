################################################################################
# Variables
################################################################################

variable "aws_region" {
  description = "AWS region to deploy resources"
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Project name prefix for all resources"
  type        = string
  default     = "scf-agent"
}

variable "bedrock_model_id" {
  description = "Bedrock foundation model ID for agent reasoning"
  type        = string
  default     = "anthropic.claude-sonnet-4-20250514-v1:0"
}

variable "embedding_model_id" {
  description = "Bedrock embedding model for knowledge base"
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "log_level" {
  description = "Application log level"
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR"], var.log_level)
    error_message = "log_level must be one of: DEBUG, INFO, WARNING, ERROR"
  }
}

variable "notification_email" {
  description = "Email address for SCF update notifications (leave empty to skip)"
  type        = string
  default     = ""
}

################################################################################
# A2A (Agent-to-Agent) ingress
################################################################################

variable "enable_a2a" {
  description = "Provision the API Gateway HTTP API + bridge Lambda that accept incoming A2A connections"
  type        = bool
  default     = true
}

variable "agent_public_name" {
  description = "Human-readable agent name published in the A2A Agent Card"
  type        = string
  default     = "SCF Compliance Assessment Agent"
}

variable "cognito_a2a_domain_prefix" {
  description = "Globally-unique prefix for the Cognito hosted-UI domain (<prefix>.auth.<region>.amazoncognito.com)"
  type        = string
  default     = "scf-agent-a2a"

  validation {
    condition     = can(regex("^[a-z0-9-]{3,63}$", var.cognito_a2a_domain_prefix))
    error_message = "cognito_a2a_domain_prefix must be 3-63 chars of lowercase letters, digits, or hyphens."
  }
}

variable "cognito_a2a_web_callback_urls" {
  description = "Allowed callback/logout URLs for the interactive (authorization_code) Cognito app client"
  type        = list(string)
  default     = ["http://localhost:8501/"]
}

variable "entra_tenant_id" {
  description = "Microsoft Entra ID tenant (directory) ID. Leave empty to skip the Entra-authorized route."
  type        = string
  default     = ""
}

variable "entra_audience" {
  description = "Expected `aud` for Entra tokens - the App ID URI or client ID of this API's Entra app registration"
  type        = string
  default     = ""
}

variable "entra_issuer_override" {
  description = "Override the Entra issuer (e.g. https://sts.windows.net/<tid>/ for v1.0 tokens). Empty = v2.0 issuer."
  type        = string
  default     = ""
}

variable "a2a_custom_domain" {
  description = "Optional custom domain for the A2A API (e.g. a2a.example.com). Empty = use the generated execute-api URL. Only affects URLs published in the Agent Card; the domain/cert/mapping are managed outside this config."
  type        = string
  default     = ""
}
