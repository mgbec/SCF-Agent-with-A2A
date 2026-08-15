"""
Audit Logger Lambda

Processes DynamoDB Stream events from the approved answers table and writes
a complete audit trail to the audit log table.

Each audit record includes:
- What changed (INSERT, MODIFY, REMOVE)
- Who changed it (from the record's approved_by field)
- When it changed
- Before/after values for modifications
- The full answer content
"""

import json
import logging
import os
import uuid
from datetime import datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

AUDIT_TABLE = os.environ["AUDIT_TABLE"]

dynamodb = boto3.resource("dynamodb")
audit_table = dynamodb.Table(AUDIT_TABLE)


def lambda_handler(event, context):
    """Process DynamoDB Stream records."""
    records_processed = 0

    for record in event.get("Records", []):
        try:
            process_record(record)
            records_processed += 1
        except Exception as e:
            logger.error(f"Failed to process record: {e}", exc_info=True)

    logger.info(f"Processed {records_processed} audit records")
    return {"statusCode": 200, "processed": records_processed}


def process_record(record: dict):
    """Process a single DynamoDB Stream record."""
    event_name = record.get("eventName", "UNKNOWN")  # INSERT, MODIFY, REMOVE
    timestamp = datetime.utcnow().isoformat() + "Z"

    new_image = deserialize(record.get("dynamodb", {}).get("NewImage", {}))
    old_image = deserialize(record.get("dynamodb", {}).get("OldImage", {}))

    answer_id = new_image.get("answer_id") or old_image.get("answer_id", "unknown")

    # Build audit entry
    audit_entry = {
        "audit_id": str(uuid.uuid4()),
        "answer_id": answer_id,
        "timestamp": timestamp,
        "event_type": event_name,
        "changed_by": new_image.get("approved_by") or old_image.get("approved_by", "system"),
    }

    if event_name == "INSERT":
        audit_entry["action"] = "Answer created"
        audit_entry["new_value"] = {
            "question": new_image.get("question_text", ""),
            "answer": new_image.get("answer_text", ""),
            "category": new_image.get("category", ""),
            "framework": new_image.get("source_framework", ""),
            "status": new_image.get("status", ""),
        }

    elif event_name == "MODIFY":
        audit_entry["action"] = "Answer modified"
        audit_entry["old_value"] = {
            "question": old_image.get("question_text", ""),
            "answer": old_image.get("answer_text", ""),
            "status": old_image.get("status", ""),
        }
        audit_entry["new_value"] = {
            "question": new_image.get("question_text", ""),
            "answer": new_image.get("answer_text", ""),
            "status": new_image.get("status", ""),
        }
        # Identify what specifically changed
        changes = []
        if old_image.get("answer_text") != new_image.get("answer_text"):
            changes.append("answer_text")
        if old_image.get("status") != new_image.get("status"):
            changes.append(f"status: {old_image.get('status')} -> {new_image.get('status')}")
        if old_image.get("approved_by") != new_image.get("approved_by"):
            changes.append("approved_by")
        audit_entry["fields_changed"] = ", ".join(changes) if changes else "metadata"

    elif event_name == "REMOVE":
        audit_entry["action"] = "Answer deleted"
        audit_entry["old_value"] = {
            "question": old_image.get("question_text", ""),
            "answer": old_image.get("answer_text", ""),
            "category": old_image.get("category", ""),
        }

    # Write to audit table
    # Remove empty strings (DynamoDB doesn't allow them)
    audit_entry = {k: v for k, v in audit_entry.items() if v != "" and v is not None}
    audit_table.put_item(Item=audit_entry)

    logger.info(f"Audit: {event_name} on {answer_id} by {audit_entry.get('changed_by', 'unknown')}")


def deserialize(image: dict) -> dict:
    """Convert DynamoDB stream format to plain dict."""
    if not image:
        return {}

    result = {}
    for key, value in image.items():
        if "S" in value:
            result[key] = value["S"]
        elif "N" in value:
            result[key] = value["N"]
        elif "BOOL" in value:
            result[key] = value["BOOL"]
        elif "NULL" in value:
            result[key] = None
        elif "M" in value:
            result[key] = deserialize(value["M"])
        elif "L" in value:
            result[key] = [deserialize({"v": item})["v"] if isinstance(item, dict) else item for item in value["L"]]
        else:
            result[key] = str(value)
    return result
