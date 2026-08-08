"""
Web Research Tools

Provides supplementary live web search for current information.
Falls back gracefully if web search is not available.

NOTE: The AgentCore Web Search connector requires console setup.
If not configured, these tools return a helpful message directing
the user to the SCF website for current information.
"""

import json
import logging
import os

import boto3
from strands import tool

logger = logging.getLogger(__name__)


def _web_search_available() -> bool:
    """Check if web search gateway is configured and reachable."""
    return bool(os.environ.get("GATEWAY_ID"))


@tool
def search_regulatory_updates(regulation: str, topic: str = "") -> str:
    """
    Search for the latest regulatory guidance, enforcement actions, or updates.

    Args:
        regulation: The regulation or framework (e.g., 'HIPAA', 'NIS2', 'PCI DSS 4.0')
        topic: Optional topic (e.g., 'enforcement action', 'new guidance', 'deadline')

    Returns:
        Latest information or guidance on where to find it
    """
    if not _web_search_available():
        return json.dumps({
            "status": "web_search_not_configured",
            "suggestion": f"For latest {regulation} updates, check: "
                         f"hhs.gov (HIPAA), nist.gov (NIST), enisa.europa.eu (NIS2), "
                         f"pcisecuritystandards.org (PCI DSS). "
                         f"The SCF data in this system reflects version 2026.2.",
        })

    # Attempt gateway-based search
    return _invoke_web_search(f"{regulation} {topic} compliance update 2026".strip())


@tool
def search_vulnerability_intelligence(query: str) -> str:
    """
    Search for current vulnerability or threat intelligence.

    Args:
        query: The vulnerability or threat (e.g., 'CVE-2026-1234', 'CISA KEV latest')

    Returns:
        Vulnerability information or guidance on where to find it
    """
    if not _web_search_available():
        return json.dumps({
            "status": "web_search_not_configured",
            "suggestion": f"For vulnerability data, check: "
                         f"nvd.nist.gov, cisa.gov/known-exploited-vulnerabilities-catalog, "
                         f"and cve.org. Query: {query}",
        })

    return _invoke_web_search(f"{query} vulnerability security advisory")


@tool
def search_breach_cases(industry: str = "healthcare", control_area: str = "") -> str:
    """
    Search for recent data breach cases and enforcement outcomes.

    Args:
        industry: Industry focus (e.g., 'healthcare', 'financial')
        control_area: Optional area (e.g., 'access control', 'encryption', 'vendor')

    Returns:
        Breach case information or guidance on where to find it
    """
    if not _web_search_available():
        return json.dumps({
            "status": "web_search_not_configured",
            "suggestion": f"For {industry} breach data, check: "
                         f"hhs.gov/hipaa/for-professionals/breach-notification (HIPAA), "
                         f"ico.org.uk/action-weve-taken (UK), "
                         f"haveibeenpwned.com for breach databases.",
        })

    return _invoke_web_search(f"{industry} data breach {control_area} enforcement 2026".strip())


@tool
def search_best_practices(topic: str, organization_size: str = "medium") -> str:
    """
    Search for current industry best practices and implementation guides.

    Args:
        topic: Security/compliance topic (e.g., 'zero trust', 'AI governance', 'SBOM')
        organization_size: Org size context ('small', 'medium', 'large', 'enterprise')

    Returns:
        Best practice guidance or references to find it
    """
    if not _web_search_available():
        return json.dumps({
            "status": "web_search_not_configured",
            "suggestion": f"For {topic} best practices, check: "
                         f"nist.gov, cisa.gov, sans.org, csoonline.com. "
                         f"The SCF Practitioner Guidebook also has implementation guidance: "
                         f"securecontrolsframework.com/free-content/scf-download",
        })

    return _invoke_web_search(f"{topic} best practices {organization_size} implementation guide")


def _invoke_web_search(query: str) -> str:
    """Invoke web search through the AgentCore Gateway."""
    gateway_id = os.environ.get("GATEWAY_ID")

    try:
        client = boto3.client(
            "bedrock-agentcore",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
        response = client.invoke_gateway(
            gatewayIdentifier=gateway_id,
            toolName="WebSearch",
            toolInput=json.dumps({"query": query[:200], "maxResults": 5}),
        )
        result = json.loads(response["body"].read().decode("utf-8"))
        return json.dumps({
            "source": "web_search",
            "query": query,
            "results": result.get("results", []),
        }, indent=2)
    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return json.dumps({
            "status": "web_search_error",
            "error": str(e),
            "suggestion": "Web search is not available. Use the SCF data in DynamoDB for control information.",
        })
