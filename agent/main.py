"""
SCF Compliance Assessment Agent - Bedrock AgentCore Runtime Entry Point

This agent provides agentic compliance assessment capabilities using the
Secure Controls Framework (SCF) 2026.2 as its knowledge base. It can:
- Look up SCF controls by ID, domain, or keyword
- Map controls between SCF and 252+ external frameworks
- Assess organizational maturity using SCR-CMM Levels 0-5
- Perform gap analysis against target compliance frameworks
- Correlate controls with risk scenarios and threats
"""

import json
import logging
import os

from strands import Agent
from strands.models.bedrock import BedrockModel
from strands_agents_tools.http_server import start_server

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

# Configure logging
log_level = os.environ.get("LOG_LEVEL", "INFO")
logging.basicConfig(level=getattr(logging, log_level))
logger = logging.getLogger(__name__)

# Agent system prompt
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

def create_agent() -> Agent:
    """Create and configure the SCF compliance agent."""
    model = BedrockModel(
        model_id=os.environ.get("BEDROCK_MODEL_ID", "anthropic.claude-sonnet-4-20250514-v1:0"),
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )

    agent = Agent(
        model=model,
        system_prompt=SYSTEM_PROMPT,
        tools=[
            # Core SCF knowledge base tools
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
            # Web research tools (supplementary - live internet)
            search_regulatory_updates,
            search_vulnerability_intelligence,
            search_breach_cases,
            search_best_practices,
        ],
    )

    return agent


# Create global agent instance
agent = create_agent()


def handler(event: dict) -> dict:
    """
    AgentCore Runtime handler - processes incoming requests.

    Args:
        event: Request payload with 'prompt' and optional 'session_id'

    Returns:
        Response with agent output
    """
    prompt = event.get("prompt", "")
    session_id = event.get("session_id", "default")

    logger.info(f"Processing request for session: {session_id}")

    try:
        result = agent(prompt)
        return {
            "statusCode": 200,
            "body": {
                "response": str(result),
                "session_id": session_id,
            },
        }
    except Exception as e:
        logger.error(f"Agent execution error: {e}", exc_info=True)
        return {
            "statusCode": 500,
            "body": {"error": str(e)},
        }


if __name__ == "__main__":
    # Start HTTP server for AgentCore Runtime
    logger.info("Starting SCF Compliance Agent on port 8080...")
    start_server(handler, port=8080)
