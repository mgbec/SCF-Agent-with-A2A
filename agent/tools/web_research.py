"""
Web Research Tools

Uses Bedrock AgentCore Web Search (via Gateway connector) to supplement the
static SCF knowledge base with current information from the web:
- Latest regulatory guidance and enforcement actions
- Current vulnerability/CVE data from NIST NVD and CISA KEV
- Recent breach notifications and case studies
- Framework update announcements
- Industry best practices and analyst guidance
"""

import json
import logging
import os
from typing import Optional

import boto3
from strands import tool

logger = logging.getLogger(__name__)


def _get_gateway_client():
    """Get a boto3 client for the AgentCore Gateway (MCP web search)."""
    return boto3.client(
        "bedrock-agentcore",
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )


def _invoke_web_search(query: str, max_results: int = 5, domain_filter: Optional[dict] = None) -> dict:
    """
    Invoke the Web Search tool through the AgentCore Gateway.

    The Gateway exposes Web Search as an MCP tool. We call it via the
    gateway invoke API.
    """
    gateway_id = os.environ.get("GATEWAY_ID")
    if not gateway_id:
        return {"error": "GATEWAY_ID environment variable not set"}

    client = _get_gateway_client()

    # Build the tool call payload
    tool_input = {
        "query": query[:200],  # Web search query limit
        "maxResults": max_results,
    }

    if domain_filter:
        tool_input["filters"] = {"domainFilter": domain_filter}

    try:
        response = client.invoke_gateway(
            gatewayIdentifier=gateway_id,
            toolName="WebSearch",
            toolInput=json.dumps(tool_input),
        )

        result = json.loads(response["body"].read().decode("utf-8"))
        return result
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return {"error": str(e), "fallback": "Web search unavailable. Using local SCF knowledge base only."}


@tool
def search_regulatory_updates(regulation: str, topic: str = "") -> str:
    """
    Search for the latest regulatory guidance, enforcement actions, or updates
    for a specific compliance framework or regulation.

    Args:
        regulation: The regulation or framework to search for
                   (e.g., 'HIPAA', 'NIS2', 'NIST 800-53', 'PCI DSS 4.0', 'EU AI Act')
        topic: Optional topic to narrow the search
               (e.g., 'enforcement action', 'implementation deadline', 'new guidance')

    Returns:
        Latest web results with titles, snippets, URLs, and publication dates
    """
    query = f"{regulation} {topic} compliance update 2026".strip()

    # Prefer authoritative sources
    result = _invoke_web_search(
        query=query,
        max_results=8,
        domain_filter={
            "include": [
                "nist.gov", "hhs.gov", "cisa.gov", "sec.gov",
                "enisa.europa.eu", "ico.org.uk",
                "federalregister.gov", "congress.gov",
                "iso.org", "pcisecuritystandards.org",
                "securecontrolsframework.com",
                "healthit.gov", "cms.gov",
            ]
        },
    )

    if "error" in result:
        return json.dumps({
            "query": query,
            "status": "web_search_unavailable",
            "message": result.get("fallback", result["error"]),
            "recommendation": "Refer to the local SCF 2026.2 knowledge base for control mappings."
        }, indent=2)

    return json.dumps({
        "query": query,
        "source": "bedrock_agentcore_web_search",
        "results": result.get("results", []),
        "note": "Results from authoritative government and standards body sources."
    }, indent=2)


@tool
def search_vulnerability_intelligence(query: str) -> str:
    """
    Search for current vulnerability, CVE, or threat intelligence information.

    Args:
        query: The vulnerability or threat to research
               (e.g., 'CVE-2026-1234', 'Log4Shell remediation status',
                'CISA KEV latest additions', 'ransomware healthcare 2026')

    Returns:
        Latest vulnerability and threat intelligence from authoritative sources
    """
    search_query = f"{query} vulnerability security advisory"

    result = _invoke_web_search(
        query=search_query,
        max_results=8,
        domain_filter={
            "include": [
                "nvd.nist.gov", "cisa.gov", "cve.org",
                "cert.org", "us-cert.gov",
                "mitre.org", "attack.mitre.org",
                "kb.cert.org",
            ]
        },
    )

    if "error" in result:
        return json.dumps({
            "query": search_query,
            "status": "web_search_unavailable",
            "message": result.get("fallback", result["error"]),
        }, indent=2)

    return json.dumps({
        "query": search_query,
        "source": "bedrock_agentcore_web_search",
        "results": result.get("results", []),
        "note": "Results from NVD, CISA, MITRE, and CERT sources."
    }, indent=2)


@tool
def search_breach_cases(industry: str = "healthcare", control_area: str = "") -> str:
    """
    Search for recent data breach cases, enforcement actions, or incident
    reports relevant to compliance assessment.

    Args:
        industry: Industry to focus on (e.g., 'healthcare', 'financial', 'technology')
        control_area: Optional SCF domain or control area
                     (e.g., 'access control', 'encryption', 'vendor management',
                      'incident response', 'data protection')

    Returns:
        Recent breach case summaries with regulatory outcomes
    """
    query = f"{industry} data breach {control_area} enforcement 2025 2026".strip()

    result = _invoke_web_search(
        query=query,
        max_results=6,
    )

    if "error" in result:
        return json.dumps({
            "query": query,
            "status": "web_search_unavailable",
            "message": result.get("fallback", result["error"]),
        }, indent=2)

    return json.dumps({
        "query": query,
        "source": "bedrock_agentcore_web_search",
        "results": result.get("results", []),
        "note": "Use breach cases to illustrate real-world consequences of control gaps."
    }, indent=2)


@tool
def search_best_practices(topic: str, organization_size: str = "medium") -> str:
    """
    Search for current industry best practices, implementation guides, or
    analyst recommendations for a security/compliance topic.

    Args:
        topic: The security or compliance topic to research
               (e.g., 'zero trust architecture', 'AI governance framework',
                'post-quantum cryptography migration', 'SBOM implementation',
                'security metrics program')
        organization_size: Organization size context
                          ('small', 'medium', 'large', 'enterprise')

    Returns:
        Best practice guidance from industry sources
    """
    size_context = {
        "small": "SMB small business",
        "medium": "mid-size organization",
        "large": "large enterprise",
        "enterprise": "enterprise fortune 500",
    }.get(organization_size, "organization")

    query = f"{topic} best practices {size_context} implementation guide"

    result = _invoke_web_search(
        query=query,
        max_results=8,
    )

    if "error" in result:
        return json.dumps({
            "query": query,
            "status": "web_search_unavailable",
            "message": result.get("fallback", result["error"]),
        }, indent=2)

    return json.dumps({
        "query": query,
        "source": "bedrock_agentcore_web_search",
        "results": result.get("results", []),
        "note": "Supplement SCF control guidance with current industry practices."
    }, indent=2)
