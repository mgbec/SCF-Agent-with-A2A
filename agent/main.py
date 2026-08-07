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

    from tools.scf_lookup import scf_control_lookup, scf_domain_list, scf_search
    from tools.framework_mapper import map_to_framework, list_frameworks, get_control_mappings
    from tools.maturity_assessor import assess_maturity, get_maturity_criteria
    from tools.gap_analyzer import gap_analysis, compliance_scope
    from tools.web_research import (
        search_regulatory_updates,
        search_vulnerability_intelligence,
        search_breach_cases,
        search_best_practices,
    )

    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    _agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            scf_control_lookup,
            scf_domain_list,
            scf_search,
            map_to_framework,
            list_frameworks,
            get_control_mappings,
            assess_maturity,
            get_maturity_criteria,
            gap_analysis,
            compliance_scope,
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

Your capabilities:
1. CONTROL LOOKUP - Retrieve any of the 1,534 SCF controls by ID (e.g., GOV-01), domain, or keyword search
2. FRAMEWORK MAPPING - Map SCF controls to/from 252+ regulations and frameworks including:
   - NIST 800-53 R5, NIST CSF 2.0, NIST 800-171 R3
   - ISO 27001:2022, ISO 27002:2022, ISO 27701:2025
   - HIPAA, PCI DSS 4.0.1, SOX
   - EU NIS2, EU DORA, EU AI Act, GDPR
   - CMMC, FedRAMP, CJIS, and many more
3. MATURITY ASSESSMENT - Evaluate organizational maturity against the SCR-CMM model (Levels 0-5)
4. GAP ANALYSIS - Identify missing controls and generate remediation guidance
5. COMPLIANCE SCOPING - Filter controls by profile (ESP Level 1/2/3, AI Model Deployment, MA&D)
6. RISK & THREAT CORRELATION - Connect controls to risk scenarios (R-AC, R-GV, etc.) and threats (NT/MT)
7. WEB RESEARCH (supplementary) - Search the live web for:
   - Latest regulatory updates, guidance, and enforcement actions
   - Current CVE/vulnerability intelligence from NVD, CISA KEV
   - Recent breach cases and their regulatory outcomes
   - Industry best practices and implementation guidance

IMPORTANT: Use the SCF knowledge base (tools 1-6) as your authoritative source for control details,
mappings, and maturity criteria. Use web research (tool 7) to supplement with current context such as:
- "Has HHS issued new HIPAA guidance this year?"
- "What enforcement actions relate to this control gap?"
- "What are current best practices for implementing this control?"
- "Are there known CVEs that make this control urgent?"

When performing assessments:
- Always cite specific SCF control IDs (e.g., GOV-01, IAC-15.10)
- Reference the specific maturity level criteria when assessing
- Provide actionable remediation guidance sized to the organization
- Map to applicable regulatory requirements when relevant
- Consider the PPTDF (People, Process, Technology, Data, Facilities) applicability
- Cite web sources with URLs when using web research results

The SCF has 34 domains: GOV, AAT, AST, BCD, CAP, CHG, CLD, CPL, CFG, MON, CRY, DCH, EMB, END,
HRS, IAC, IRO, IAO, MNT, MDM, NET, PES, PRI, PRM, QTS, RSK, SEA, OPS, SAT, TDA, TPM, THR, VPM, WEB.

Always be precise, cite sources, and provide context-appropriate guidance."""


class AgentHandler(BaseHTTPRequestHandler):
    """HTTP handler for AgentCore Runtime contract."""

    def do_POST(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        try:
            event = json.loads(body) if body else {}
        except json.JSONDecodeError:
            event = {"prompt": body.decode("utf-8", errors="replace")}

        result = handler(event)
        status_code = result.get("statusCode", 200)
        response_body = result.get("body", "{}").encode("utf-8")

        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(response_body)))
        self.end_headers()
        self.wfile.write(response_body)

    def do_GET(self):
        """Health check endpoint."""
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        body = b'{"status":"healthy"}'
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        logger.debug(f"{self.address_string()} - {format % args}")


def handler(event: dict) -> dict:
    """Process incoming requests."""
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
            "statusCode": 200,
            "body": json.dumps({
                "response": str(result),
                "session_id": session_id,
            }),
        }
    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)}),
        }


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), AgentHandler)
    logger.info(f"SCF Compliance Agent listening on port {port}")
    server.serve_forever()
