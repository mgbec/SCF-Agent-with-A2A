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
