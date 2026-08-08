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
7. search_regulatory_updates - Search the web for latest regulatory news
8. search_vulnerability_intelligence - Search for current CVE/threat data
9. search_breach_cases - Find recent breach cases and enforcement actions
10. search_best_practices - Get current industry implementation guidance

HOW TO HANDLE REQUESTS:
- Step 1: Use KB search tools (1-4) to FIND relevant controls quickly
- Step 2: Use DynamoDB tools (5-6) to GET full details for those specific controls
- This two-step approach is fast AND complete
- For gap analysis: search by framework → get full details for matched controls
- For maturity assessment: search maturity → get full criteria from DynamoDB
- Never skip step 2 if the user needs maturity criteria or evidence details

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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    logger.info(f"SCF Compliance Agent listening on port {port}")
    server.serve_forever()
