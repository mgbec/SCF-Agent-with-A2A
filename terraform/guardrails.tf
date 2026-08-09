################################################################################
# Bedrock Guardrails - Protects against prompt injection and misuse
################################################################################

resource "aws_bedrock_guardrail" "scf_agent" {
  name                      = "${local.name_prefix}-guardrail"
  description               = "Guardrail for SCF Compliance Agent - prevents prompt injection, off-topic use, and PII leakage"
  blocked_input_messaging   = "I can only help with cybersecurity compliance, governance, and risk management topics. Please rephrase your question."
  blocked_outputs_messaging = "I cannot provide that type of response. Please ask about SCF controls, compliance frameworks, or security assessments."

  # Content filters - block harmful content
  content_policy_config {
    filters_config {
      type            = "HATE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "INSULTS"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "SEXUAL"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "VIOLENCE"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "MISCONDUCT"
      input_strength  = "HIGH"
      output_strength = "HIGH"
    }
    filters_config {
      type            = "PROMPT_ATTACK"
      input_strength  = "HIGH"
      output_strength = "NONE"
    }
  }

  # Topic policy - keep the agent on-topic
  topic_policy_config {
    topics_config {
      name       = "off_topic"
      definition = "Questions unrelated to cybersecurity, compliance, governance, risk management, security controls, auditing, or regulatory frameworks"
      type       = "DENY"

      examples = [
        "Write me a poem about cats",
        "Help me with my homework",
        "What's the weather today",
        "Tell me a joke",
        "Write code for a video game",
      ]
    }
    topics_config {
      name       = "harmful_security"
      definition = "Requests for help with hacking, exploiting vulnerabilities, creating malware, or bypassing security controls"
      type       = "DENY"

      examples = [
        "How do I hack into a system",
        "Write me an exploit for this CVE",
        "Help me bypass MFA",
        "How to exfiltrate data without detection",
      ]
    }
  }

  # Sensitive information filters
  sensitive_information_policy_config {
    pii_entities_config {
      type   = "EMAIL"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "PHONE"
      action = "ANONYMIZE"
    }
    pii_entities_config {
      type   = "US_SOCIAL_SECURITY_NUMBER"
      action = "BLOCK"
    }
    pii_entities_config {
      type   = "CREDIT_DEBIT_CARD_NUMBER"
      action = "BLOCK"
    }
  }

  tags = {
    Component = "security"
  }
}

resource "aws_bedrock_guardrail_version" "scf_agent" {
  guardrail_arn = aws_bedrock_guardrail.scf_agent.guardrail_arn
  description   = "Initial version"
}
