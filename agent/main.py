"""
SCF Compliance Assessment Agent - Bedrock AgentCore Runtime Entry Point

This agent provides agentic compliance assessment capabilities using the
Secure Controls Framework (SCF) 2026.2 as its knowledge base.
"""

import json
import logging
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

# Configure logging immediately (no heavy imports yet)
log_level = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# Lazy-loaded agent instance
_agent = None


def _get_agent():
    """Lazy-initialize the agent on first request (not at import time)."""
    global _agent
    if _agent is not None:
        return _agent

    logger.info("Initializing SCF Compliance Agent...")
    from strands import Agent
    from strands.models.bedrock import BedrockModel

    from tools.kb_retrieval import (
        search_scf_controls,
        search_scf_by_framework,
        get_scf_control_details,
        search_scf_maturity,
    )
    from tools.dynamo_lookup import (
        get_control_full_details,
        get_controls_by_domain,
    )
    from tools.memory import (
        remember_organization_context,
        recall_organization_context,
    )
    from tools.answers_lookup import (
        search_approved_answers,
        get_answer_by_id,
        list_answer_categories,
    )
    from tools.web_research import (
        search_regulatory_updates,
        search_vulnerability_intelligence,
        search_breach_cases,
        search_best_practices,
    )

    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "us.anthropic.claude-sonnet-4-6"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    _agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            # KB search (fast vector retrieval - finds relevant controls)
            search_scf_controls,
            search_scf_by_framework,
            get_scf_control_details,
            search_scf_maturity,
            # DynamoDB (full detail retrieval - complete data, no size limits)
            get_control_full_details,
            get_controls_by_domain,
            # Approved answers (historical questionnaire responses)
            search_approved_answers,
            get_answer_by_id,
            list_answer_categories,
            # Long-term memory (persists across sessions)
            remember_organization_context,
            recall_organization_context,
            # Web research (supplementary - live internet)
            search_regulatory_updates,
            search_vulnerability_intelligence,
            search_breach_cases,
            search_best_practices,
        ],
    )
    logger.info("Agent initialized successfully")
    return _agent


SYSTEM_PROMPT = """You are a Secure Controls Framework (SCF) 2026.2 Compliance Assessment Agent.
You are an expert in cybersecurity governance, risk management, and compliance (GRC).

You have access to a Knowledge Base containing the complete SCF 2026.2 framework data:
- 1,534 controls across 34 domains
- Mappings to 252+ regulations and frameworks (HIPAA, NIST, ISO, PCI DSS, NIS2, DORA, etc.)
- SCR-CMM maturity criteria (Levels 0-5) for every control
- Risk and threat correlations
- Size-appropriate implementation guidance

YOUR TOOLS:
1. search_scf_controls - Search the KB for relevant controls (fast, use for discovery)
2. search_scf_by_framework - Find controls mapped to a specific regulation
3. get_scf_control_details - Quick KB lookup for a specific control ID
4. search_scf_maturity - Find maturity criteria for a domain
5. get_control_full_details - Get COMPLETE data from DynamoDB (full maturity criteria, all mappings)
6. get_controls_by_domain - Get all controls in a domain from DynamoDB
7. search_approved_answers - Find historical questionnaire answers by topic, category, or framework
8. get_answer_by_id - Get a specific approved answer by ID
9. list_answer_categories - Browse available answer categories and frameworks
10. remember_organization_context - Save org info to long-term memory
11. recall_organization_context - Load org info from previous sessions
12. search_regulatory_updates - Search the web for latest regulatory news
13. search_vulnerability_intelligence - Search for current CVE/threat data
14. search_breach_cases - Find recent breach cases and enforcement actions
15. search_best_practices - Get current industry implementation guidance

HOW TO HANDLE REQUESTS:
- FIRST: Call recall_organization_context to check if you already know about this user
- For SCF control questions: KB search then DynamoDB full details
- For questionnaire help: search_approved_answers FIRST, then supplement with SCF data
- For gap analysis: search by framework, get full details, compare against user controls
- SAVE: When the user shares org info, use remember_organization_context

QUESTIONNAIRE ANSWERS:
- When users ask how to answer a compliance question, ALWAYS check approved answers first
- If a matching approved answer exists, present it with the source citation
- If no match, draft a new answer based on SCF controls and best practices
- Always note the source framework and approval date of historical answers

NOTE ON DATA: Maturity criteria in KB search results are summarized. Use 
get_control_full_details for complete SCR-CMM level criteria. For the absolute 
full text, refer users to securecontrolsframework.com/free-content/scf-download

RESPONSE FORMAT:
- Keep responses focused and under 4000 tokens
- If a question requires extensive detail, provide a solid summary with the most
  important findings, then offer: "Would you like me to go deeper on any of these?"
- When asked for more detail, expand on 2-3 items at a time (not all at once)
- Never try to output a 10+ item detailed report in a single response
- Use tables for structured data, headers for sections
- Always cite specific SCF control IDs (e.g., GOV-01, IAC-15.10)
- Reference maturity level criteria when assessing
- Provide actionable remediation guidance sized to the organization

The SCF has 34 domains: GOV, AAT, AST, BCD, CAP, CHG, CLD, CPL, CFG, MON, CRY, DCH, EMB, END,
HRS, IAC, IRO, IAO, MNT, MDM, NET, PES, PRI, PRM, QTS, RSK, SEA, OPS, SAT, TDA, TPM, THR, VPM, WEB."""


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP handler for AgentCore Runtime contract.

    AgentCore requires:
    - POST /invocations - process agent requests
    - GET /ping - health check (return {"status": "Healthy"})
    """

    def do_POST(self):
        if self.path != "/invocations":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            event = json.loads(body) if body else {}
        except json.JSONDecodeError:
            event = {"prompt": body.decode("utf-8", errors="replace")}

        result = handler(event)
        response_body = json.dumps(result).encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def do_GET(self):
        if self.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            body = b'{"status":"Healthy"}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"error":"not found"}')

    def log_message(self, format, *args):
        logger.info(f"HTTP: {self.address_string()} - {format % args}")


def handler(event: dict) -> dict:
    """Process incoming requests. Returns AgentCore-compatible JSON response."""
    prompt = (
        event.get("prompt")
        or event.get("input")
        or event.get("message")
        or event.get("query")
        or json.dumps(event)
    )
    session_id = event.get("session_id", "default")

    # Input validation
    validation_error = _validate_input(prompt)
    if validation_error:
        logger.warning(f"Input rejected: {validation_error}")
        return {
            "response": validation_error,
            "status": "rejected",
        }

    logger.info(f"Processing request for session: {session_id}, prompt length: {len(prompt)}")

    try:
        agent = _get_agent()
        result = agent(prompt)
        return {
            "response": str(result),
            "session_id": session_id,
            "status": "success",
        }
    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        return {
            "response": f"Error: {str(e)}",
            "status": "error",
        }


def _validate_input(prompt: str) -> str:
    """
    Validate user input before sending to the model.
    Returns error message if invalid, empty string if OK.
    """
    # Length limits
    if len(prompt) > 10000:
        return "Input too long. Please keep your question under 10,000 characters."

    if len(prompt.strip()) == 0:
        return "Empty input. Please provide a question about SCF compliance."

    # Basic injection detection
    injection_patterns = [
        "ignore previous instructions",
        "ignore all previous",
        "disregard your instructions",
        "you are now",
        "new instructions:",
        "system prompt:",
        "forget everything",
        "override your",
    ]
    prompt_lower = prompt.lower()
    for pattern in injection_patterns:
        if pattern in prompt_lower:
            logger.warning(f"Potential injection attempt detected: '{pattern}'")
            return "I can only help with cybersecurity compliance topics. Please rephrase your question."

    # Off-topic detection - check if the prompt has NO compliance-related keywords
    compliance_keywords = [
        "scf", "control", "compliance", "security", "risk", "audit", "framework",
        "hipaa", "nist", "iso", "pci", "soc", "gdpr", "nis2", "dora", "cmmc",
        "maturity", "gap", "assessment", "policy", "governance", "encryption",
        "access", "incident", "vulnerability", "patch", "privacy", "data",
        "network", "identity", "authentication", "monitoring", "continuity",
        "vendor", "third-party", "supply chain", "quantum", "ai", "cloud",
        "endpoint", "malware", "phishing", "training", "awareness", "evidence",
        "remediation", "compensating", "domain", "implement", "requirement",
    ]
    has_compliance_keyword = any(kw in prompt_lower for kw in compliance_keywords)

    # If no compliance keywords AND it's clearly off-topic
    off_topic_patterns = [
        "poem", "story", "joke", "recipe", "weather", "sports",
        "movie", "song", "game", "homework", "essay about",
        "write me a", "tell me a joke", "what's the score",
    ]
    is_off_topic = any(pattern in prompt_lower for pattern in off_topic_patterns)

    if is_off_topic and not has_compliance_keyword:
        return ("I'm the SCF Compliance Assessment Agent — I help with cybersecurity governance, "
                "risk management, and compliance. I can help with gap analysis, maturity assessments, "
                "framework mapping, and evidence requirements. How can I help with your compliance needs?")

    return ""


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    logger.info(f"SCF Compliance Agent listening on port {port}")
    server.serve_forever()
