"""
Approved Answers Lookup Tools

Searches and retrieves historical questionnaire answers, assessment responses,
and compliance documentation from the approved answers database.

Use when the user asks:
- "How do we answer this SIG question about encryption?"
- "What did we put for the SOC 2 access control section?"
- "Find our standard response about incident response"
- "How did we answer the vendor questionnaire about data retention?"
"""

import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key, Attr
from strands import tool

logger = logging.getLogger(__name__)

_answers_table = None


def _get_answers_table():
    """Get the approved answers DynamoDB table."""
    global _answers_table
    if _answers_table is None:
        table_name = os.environ.get("ANSWERS_TABLE")
        if not table_name:
            return None
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        _answers_table = dynamodb.Table(table_name)
    return _answers_table


@tool
def search_approved_answers(query: str, category: str = "", framework: str = "", limit: int = 5) -> str:
    """
    Search for previously approved answers to compliance questionnaires.
    Use this when the user needs to answer a security questionnaire or assessment
    and wants to find how the organization has answered similar questions before.

    Args:
        query: The question or topic to search for (e.g., "data encryption at rest",
               "incident response process", "access control MFA", "data retention policy")
        category: Optional category filter (e.g., "encryption", "access_control",
                  "incident_response", "data_protection", "vendor_management",
                  "business_continuity", "network_security")
        framework: Optional framework filter (e.g., "SIG", "SOC2", "HITRUST",
                   "HIPAA", "vendor_questionnaire", "RFP")
        limit: Max results to return (default 5)

    Returns:
        Matching approved answers with source citations and approval metadata
    """
    table = _get_answers_table()
    if table is None:
        return json.dumps({
            "status": "not_configured",
            "message": "Approved answers database not configured. No historical questionnaire data available yet.",
        })

    try:
        # ALWAYS do keyword search first (most reliable)
        response = table.scan(Limit=100)
        
        # Split query into keywords for matching
        keywords = [w.lower() for w in query.split() if len(w) > 3]
        if not keywords:
            keywords = [query.lower()]
        
        items = []
        for item in response.get("Items", []):
            q_text = (item.get("question_text", "") or "").lower()
            a_text = (item.get("answer_text", "") or "").lower()
            tags = (item.get("tags", "") or "").lower()
            cat = (item.get("category", "") or "").lower()
            searchable = f"{q_text} {a_text} {tags} {cat}"
            
            # Apply category/framework filter if specified
            if category and category.lower() != (item.get("category", "") or "").lower():
                continue
            if framework and framework.upper() != (item.get("source_framework", "") or "").upper():
                continue
            
            # Score by keyword matches
            score = sum(1 for kw in keywords if kw in searchable)
            if score >= max(1, len(keywords) // 3):
                item["_score"] = score
                items.append(item)
        
        # Sort by relevance score
        items.sort(key=lambda x: x.get("_score", 0), reverse=True)
        items = items[:limit]

        if not items:
            return json.dumps({
                "status": "no_matches",
                "query": query,
                "message": "No approved answers found matching this query. This may be a new topic that needs a fresh response.",
                "suggestion": "I can help draft an answer based on SCF controls and best practices.",
            })

        results = []
        for item in items:
            results.append({
                "answer_id": item.get("answer_id", ""),
                "question": item.get("question_text", ""),
                "answer": item.get("answer_text", ""),
                "framework": item.get("source_framework", ""),
                "category": item.get("category", ""),
                "source_document": item.get("source_document", ""),
                "scf_controls": item.get("scf_control_ids", ""),
                "approved_by": item.get("approved_by", ""),
                "approved_date": item.get("approved_date", ""),
            })

        return json.dumps({
            "status": "found",
            "query": query,
            "result_count": len(results),
            "results": results,
        }, indent=2, default=str)

    except Exception as e:
        logger.error(f"Answer search error: {e}", exc_info=True)
        return json.dumps({"error": str(e), "query": query})


@tool
def get_answer_by_id(answer_id: str) -> str:
    """
    Retrieve a specific approved answer by its ID.

    Args:
        answer_id: The unique identifier of the answer

    Returns:
        Full answer details including approval metadata and source
    """
    table = _get_answers_table()
    if table is None:
        return json.dumps({"error": "Answers database not configured"})

    try:
        response = table.get_item(Key={"answer_id": answer_id})
        item = response.get("Item")
        if item:
            return json.dumps(item, indent=2, default=str)
        return json.dumps({"error": f"Answer '{answer_id}' not found"})
    except Exception as e:
        return json.dumps({"error": str(e)})


@tool
def list_answer_categories() -> str:
    """
    List available categories of approved answers.
    Use this when the user wants to browse what historical answers are available.

    Returns:
        List of categories with counts
    """
    table = _get_answers_table()
    if table is None:
        return json.dumps({
            "status": "not_configured",
            "message": "Approved answers database not configured yet. To populate it, upload questionnaire documents using the ingestion script.",
        })

    try:
        # Scan for unique categories (not ideal for large datasets but fine for <10K items)
        response = table.scan(
            ProjectionExpression="category, source_framework",
        )

        categories = {}
        frameworks = {}
        for item in response.get("Items", []):
            cat = item.get("category", "uncategorized")
            fw = item.get("source_framework", "unknown")
            categories[cat] = categories.get(cat, 0) + 1
            frameworks[fw] = frameworks.get(fw, 0) + 1

        return json.dumps({
            "total_answers": response.get("Count", 0),
            "categories": categories,
            "frameworks": frameworks,
        }, indent=2)

    except Exception as e:
        return json.dumps({"error": str(e)})
