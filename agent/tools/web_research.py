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
    """Invoke web search through the AgentCore MCP Gateway using SigV4-signed HTTP."""
    gateway_id = os.environ.get("GATEWAY_ID")
    region = os.environ.get("AWS_REGION", "us-east-1")
    gateway_url = f"https://{gateway_id}.gateway.bedrock-agentcore.{region}.amazonaws.com/mcp"

    try:
        import botocore.auth
        import botocore.credentials
        import botocore.session
        import urllib.request

        # Get credentials for SigV4 signing
        session = botocore.session.get_session()
        credentials = session.get_credentials().get_frozen_credentials()

        # Build MCP tools/call request
        mcp_request = json.dumps({
            "jsonrpc": "2.0",
            "id": "1",
            "method": "tools/call",
            "params": {
                "name": "WebSearch",
                "arguments": {
                    "query": query[:200],
                    "maxResults": 5,
                },
            },
        })

        # Create the HTTP request
        req = urllib.request.Request(
            gateway_url,
            data=mcp_request.encode("utf-8"),
            headers={
                "Content-Type": "application/json",
            },
            method="POST",
        )

        # Sign with SigV4
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest

        aws_req = AWSRequest(method="POST", url=gateway_url, data=mcp_request, headers={"Content-Type": "application/json"})
        SigV4Auth(credentials, "bedrock-agentcore", region).add_auth(aws_req)

        # Copy signed headers to urllib request
        for header, value in aws_req.headers.items():
            req.add_header(header, value)

        # Make the request
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))

        # Parse MCP response
        if "result" in result:
            content = result["result"].get("content", [])
            if content:
                # MCP returns content as text blocks
                text_content = content[0].get("text", "{}") if content else "{}"
                try:
                    search_results = json.loads(text_content)
                    return json.dumps({
                        "source": "web_search",
                        "query": query,
                        "results": search_results.get("results", []),
                    }, indent=2)
                except json.JSONDecodeError:
                    return json.dumps({
                        "source": "web_search",
                        "query": query,
                        "raw_result": text_content[:2000],
                    }, indent=2)

        return json.dumps({
            "source": "web_search",
            "query": query,
            "results": [],
            "note": "No results returned from web search.",
        })

    except Exception as e:
        logger.warning(f"Web search failed: {e}")
        return json.dumps({
            "status": "web_search_error",
            "error": str(e),
            "suggestion": f"Web search failed. For {query}, check nist.gov, hhs.gov, or cisa.gov directly.",
        })
