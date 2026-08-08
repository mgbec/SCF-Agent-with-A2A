"""
DynamoDB Control Detail Lookup

Retrieves full SCF control data from DynamoDB — complete maturity criteria,
all framework mappings, full solutions text. No size limits.

Use AFTER the KB search identifies relevant controls by ID.
"""

import json
import logging
import os
from typing import Optional

import boto3
from strands import tool

logger = logging.getLogger(__name__)

_dynamo_table = None


def _get_table():
    """Get the DynamoDB table resource."""
    global _dynamo_table
    if _dynamo_table is None:
        table_name = os.environ.get("DYNAMODB_TABLE")
        if not table_name:
            return None
        dynamodb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        _dynamo_table = dynamodb.Table(table_name)
    return _dynamo_table


@tool
def get_control_full_details(control_ids: str) -> str:
    """
    Get COMPLETE details for one or more SCF controls from DynamoDB.
    Returns full maturity criteria, all framework mappings, and implementation guidance.

    Use this AFTER using search_scf_controls to find relevant control IDs.

    Args:
        control_ids: Comma-separated SCF control IDs (e.g., "GOV-01,IAC-15,RSK-01")
                    Maximum 10 controls per call.

    Returns:
        Full control data including complete maturity criteria at all levels,
        all 252+ framework mappings, risk/threat correlations, and solutions
    """
    table = _get_table()
    if table is None:
        return json.dumps({"error": "DYNAMODB_TABLE not configured"})

    ids = [cid.strip().upper() for cid in control_ids.split(",") if cid.strip()]
    ids = ids[:10]  # Limit to 10

    results = []
    for scf_id in ids:
        try:
            response = table.get_item(Key={"scf_id": scf_id})
            item = response.get("Item")
            if item:
                # Convert Decimal types to int/float for JSON serialization
                results.append(_clean_item(item))
            else:
                results.append({"scf_id": scf_id, "error": "Control not found"})
        except Exception as e:
            results.append({"scf_id": scf_id, "error": str(e)})

    return json.dumps({"controls": results, "count": len(results)}, indent=2, default=str)


@tool
def get_controls_by_domain(domain_id: str) -> str:
    """
    Get all controls in a specific SCF domain from DynamoDB.

    Args:
        domain_id: The SCF domain identifier (e.g., "GOV", "IAC", "NET", "AAT", "QTS")

    Returns:
        List of all controls in the domain with full details
    """
    table = _get_table()
    if table is None:
        return json.dumps({"error": "DYNAMODB_TABLE not configured"})

    domain_id = domain_id.upper().strip()

    try:
        response = table.query(
            IndexName="domain-index",
            KeyConditionExpression=boto3.dynamodb.conditions.Key("domain_id").eq(domain_id),
        )
        items = [_clean_item(item) for item in response.get("Items", [])]
        return json.dumps({
            "domain": domain_id,
            "control_count": len(items),
            "controls": items[:20],  # Limit output to 20 controls
        }, indent=2, default=str)
    except Exception as e:
        return json.dumps({"error": str(e), "domain": domain_id})


def _clean_item(item: dict) -> dict:
    """Convert DynamoDB types for JSON serialization."""
    from decimal import Decimal
    cleaned = {}
    for key, value in item.items():
        if isinstance(value, Decimal):
            cleaned[key] = int(value) if value == int(value) else float(value)
        elif isinstance(value, dict):
            cleaned[key] = _clean_item(value)
        else:
            cleaned[key] = value
    return cleaned
