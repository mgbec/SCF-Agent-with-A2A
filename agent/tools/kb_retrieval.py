"""
Knowledge Base Retrieval Tool

Replaces the direct S3 JSON loading approach with fast vector-based retrieval
from the Bedrock Knowledge Base. Returns relevant SCF control chunks in
milliseconds instead of loading and iterating the full 22MB JSON.
"""

import json
import logging
import os

import boto3
from strands import tool

logger = logging.getLogger(__name__)

_kb_client = None


def _get_kb_client():
    """Get the Bedrock Agent Runtime client for KB retrieval."""
    global _kb_client
    if _kb_client is None:
        _kb_client = boto3.client(
            "bedrock-agent-runtime",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _kb_client


@tool
def search_scf_controls(query: str, max_results: int = 10) -> str:
    """
    Search the SCF 2026.2 Knowledge Base for controls matching a query.
    Use this for ANY question about SCF controls, frameworks, mappings, maturity criteria, or compliance.

    Args:
        query: Natural language search query. Examples:
            - "HIPAA access control requirements"
            - "GOV-01 maturity criteria"
            - "controls that map to NIST 800-53 PM-01"
            - "incident response SCR-CMM Level 3"
            - "encryption data at rest controls"
            - "third party vendor management supply chain"
            - "quantum cryptography post-quantum"
        max_results: Number of relevant control chunks to retrieve (default 10, max 25)

    Returns:
        Relevant SCF control data including descriptions, maturity criteria,
        framework mappings, and implementation guidance
    """
    kb_id = os.environ.get("KNOWLEDGE_BASE_ID")
    if not kb_id:
        return json.dumps({"error": "KNOWLEDGE_BASE_ID not configured"})

    max_results = min(max(1, max_results), 25)

    try:
        client = _get_kb_client()
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": query},
            retrievalConfiguration={
                "vectorSearchConfiguration": {
                    "numberOfResults": max_results,
                }
            },
        )

        results = []
        for item in response.get("retrievalResults", []):
            content = item.get("content", {}).get("text", "")
            score = item.get("score", 0)
            location = item.get("location", {})

            results.append({
                "content": content,
                "relevance_score": score,
                "source": location.get("s3Location", {}).get("uri", ""),
            })

        return json.dumps({
            "query": query,
            "result_count": len(results),
            "results": results,
        }, indent=2)

    except Exception as e:
        logger.error(f"KB retrieval error: {e}", exc_info=True)
        return json.dumps({"error": str(e), "query": query})


@tool
def search_scf_by_framework(framework: str, topic: str = "", max_results: int = 15) -> str:
    """
    Search for SCF controls that map to a specific compliance framework.

    Args:
        framework: The framework to search for mappings. Examples:
            - "HIPAA Security Rule"
            - "NIST 800-53"
            - "ISO 27001"
            - "PCI DSS 4.0"
            - "EU NIS2"
            - "SOC 2"
            - "CMMC"
        topic: Optional topic to narrow results (e.g., "access control", "encryption", "incident response")
        max_results: Number of results (default 15, max 25)

    Returns:
        SCF controls with their mappings to the specified framework
    """
    query = f"SCF controls mapped to {framework}"
    if topic:
        query += f" {topic}"

    return search_scf_controls(query=query, max_results=min(max_results, 25))


@tool
def get_scf_control_details(control_id: str) -> str:
    """
    Get detailed information about a specific SCF control by its ID.

    Args:
        control_id: The SCF control identifier (e.g., "GOV-01", "IAC-15", "AAT-01.5", "QTS-01")

    Returns:
        Full control details including description, maturity criteria, framework mappings,
        and implementation guidance
    """
    return search_scf_controls(
        query=f"SCF control {control_id} description maturity criteria mappings",
        max_results=5,
    )


@tool
def search_scf_maturity(domain: str, level: int = 3) -> str:
    """
    Search for maturity criteria for an SCF domain at a specific SCR-CMM level.

    Args:
        domain: SCF domain identifier or name (e.g., "GOV", "IAC", "Identity & Access Control")
        level: Target SCR-CMM maturity level (0-5, default 3)

    Returns:
        Maturity criteria for controls in the specified domain at the target level
    """
    level_names = {
        0: "Not Performed",
        1: "Performed Informally",
        2: "Planned & Tracked",
        3: "Well Defined",
        4: "Quantitatively Controlled",
        5: "Continuously Improving",
    }
    level_name = level_names.get(level, "Well Defined")

    return search_scf_controls(
        query=f"SCF {domain} domain SCR-CMM Level {level} {level_name} maturity criteria",
        max_results=10,
    )
