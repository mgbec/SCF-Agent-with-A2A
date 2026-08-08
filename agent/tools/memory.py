"""
Organization Memory Tool

Stores and retrieves organizational context across sessions using AgentCore Memory.
Remembers things like:
- Organization profile (size, industry, compliance targets)
- Implemented controls list
- Previous assessment findings
- Remediation progress
"""

import json
import logging
import os
from datetime import datetime

import boto3
from strands import tool

logger = logging.getLogger(__name__)

_memory_client = None


def _get_client():
    global _memory_client
    if _memory_client is None:
        _memory_client = boto3.client(
            "bedrock-agentcore",
            region_name=os.environ.get("AWS_REGION", "us-east-1"),
        )
    return _memory_client


def _get_memory_id():
    return os.environ.get("MEMORY_ID", "")


@tool
def remember_organization_context(key: str, value: str) -> str:
    """
    Save organizational context to long-term memory. Use this whenever the user
    shares important information about their organization that should persist
    across sessions.

    Args:
        key: What this information is about. Examples:
            - "organization_profile"
            - "implemented_controls"
            - "compliance_targets"
            - "last_assessment_findings"
            - "team_structure"
            - "infrastructure"
            - "remediation_plan"
        value: The information to remember. Be specific and structured.

    Returns:
        Confirmation that the information was saved
    """
    memory_id = _get_memory_id()
    if not memory_id:
        return json.dumps({"error": "MEMORY_ID not configured"})

    try:
        client = _get_client()
        client.put_memory(
            memoryId=memory_id,
            content={
                "text": json.dumps({
                    "key": key,
                    "value": value,
                    "saved_at": datetime.utcnow().isoformat(),
                })
            },
            metadata={
                "key": key,
                "type": "organization_context",
            },
        )
        return json.dumps({
            "status": "saved",
            "key": key,
            "message": f"Remembered: {key}. This will persist across sessions.",
        })
    except Exception as e:
        logger.error(f"Memory save error: {e}", exc_info=True)
        return json.dumps({"error": str(e), "key": key})


@tool
def recall_organization_context(query: str = "organization") -> str:
    """
    Recall previously saved organizational context from long-term memory.
    Call this at the START of a conversation to load context about the user's
    organization, or when you need to reference previously saved information.

    Args:
        query: What to search for in memory. Examples:
            - "organization" (gets everything)
            - "implemented controls"
            - "compliance targets"
            - "last assessment"
            - "remediation plan"

    Returns:
        Previously saved organizational context, or empty if nothing saved yet
    """
    memory_id = _get_memory_id()
    if not memory_id:
        return json.dumps({"error": "MEMORY_ID not configured"})

    try:
        client = _get_client()
        response = client.search_memory(
            memoryId=memory_id,
            query={"text": query},
            maxResults=10,
        )

        results = []
        for item in response.get("results", []):
            content = item.get("content", {}).get("text", "")
            try:
                parsed = json.loads(content)
                results.append(parsed)
            except json.JSONDecodeError:
                results.append({"raw": content})

        if results:
            return json.dumps({
                "status": "found",
                "context_count": len(results),
                "context": results,
            }, indent=2)
        else:
            return json.dumps({
                "status": "empty",
                "message": "No organizational context saved yet. Ask the user about their organization.",
            })
    except Exception as e:
        logger.error(f"Memory recall error: {e}", exc_info=True)
        return json.dumps({"error": str(e), "query": query})
