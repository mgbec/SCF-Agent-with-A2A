"""
Textract Document Ingestion Pipeline

Triggered by S3 upload to the questionnaire-uploads bucket.
Extracts text and tables from PDFs/images using Amazon Textract,
parses Q&A pairs, and stores them as draft answers for human approval.

Flow:
  S3 upload → EventBridge → this Lambda → Textract → Parse Q&A → DynamoDB (DRAFT)

Supported formats: PDF, PNG, JPG, TIFF
"""

import json
import logging
import os
import re
import time
import uuid
from datetime import datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

ANSWERS_TABLE = os.environ["ANSWERS_TABLE"]
UPLOADS_BUCKET = os.environ["UPLOADS_BUCKET"]
SNS_TOPIC_ARN = os.environ.get("SNS_TOPIC_ARN", "")

textract = boto3.client("textract")
dynamodb = boto3.resource("dynamodb")
sns = boto3.client("sns")
table = dynamodb.Table(ANSWERS_TABLE)


def lambda_handler(event, context):
    """
    Triggered by S3 EventBridge notification when a document is uploaded.
    """
    logger.info(f"Event: {json.dumps(event)}")

    # Extract S3 info from EventBridge event
    detail = event.get("detail", {})
    bucket = detail.get("bucket", {}).get("name", "")
    key = detail.get("object", {}).get("key", "")

    if not bucket or not key:
        # Try S3 notification format
        for record in event.get("Records", []):
            bucket = record.get("s3", {}).get("bucket", {}).get("name", "")
            key = record.get("s3", {}).get("object", {}).get("key", "")

    if not bucket or not key:
        logger.error("Could not determine S3 bucket/key from event")
        return {"statusCode": 400, "body": "No S3 object info in event"}

    logger.info(f"Processing: s3://{bucket}/{key}")

    # Determine file type
    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if ext not in ("pdf", "png", "jpg", "jpeg", "tiff", "tif"):
        logger.info(f"Skipping non-supported format: {ext}")
        return {"statusCode": 200, "body": f"Skipped: {ext} not supported for OCR"}

    # Run Textract
    try:
        if ext == "pdf":
            qa_pairs = process_pdf(bucket, key)
        else:
            qa_pairs = process_image(bucket, key)
    except Exception as e:
        logger.error(f"Textract processing failed: {e}", exc_info=True)
        notify(f"[SCF Agent] Document processing FAILED: {key}", str(e))
        return {"statusCode": 500, "body": str(e)}

    # Store as draft answers
    count = store_draft_answers(qa_pairs, key)

    # Notify
    if count > 0:
        notify(
            f"[SCF Agent] {count} draft answers extracted from {key}",
            f"Document: {key}\n"
            f"Extracted: {count} Q&A pairs\n"
            f"Status: DRAFT (requires approval)\n\n"
            f"Review and approve in the Streamlit UI or DynamoDB console."
        )

    logger.info(f"Done: {count} draft answers stored from {key}")
    return {"statusCode": 200, "body": f"Extracted {count} Q&A pairs"}


def process_pdf(bucket: str, key: str) -> list:
    """Process a multi-page PDF using async Textract."""
    logger.info("Starting async Textract job for PDF...")

    response = textract.start_document_analysis(
        DocumentLocation={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["TABLES", "FORMS"],
    )
    job_id = response["JobId"]
    logger.info(f"Textract job started: {job_id}")

    # Poll for completion
    while True:
        result = textract.get_document_analysis(JobId=job_id)
        status = result["JobStatus"]
        if status == "SUCCEEDED":
            break
        elif status == "FAILED":
            raise RuntimeError(f"Textract job failed: {result.get('StatusMessage', 'unknown')}")
        time.sleep(5)

    # Collect all pages
    blocks = result.get("Blocks", [])
    next_token = result.get("NextToken")
    while next_token:
        result = textract.get_document_analysis(JobId=job_id, NextToken=next_token)
        blocks.extend(result.get("Blocks", []))
        next_token = result.get("NextToken")

    logger.info(f"Textract returned {len(blocks)} blocks")
    return extract_qa_from_blocks(blocks)


def process_image(bucket: str, key: str) -> list:
    """Process a single image using sync Textract."""
    logger.info("Running sync Textract for image...")

    response = textract.analyze_document(
        Document={"S3Object": {"Bucket": bucket, "Name": key}},
        FeatureTypes=["TABLES", "FORMS"],
    )

    blocks = response.get("Blocks", [])
    logger.info(f"Textract returned {len(blocks)} blocks")
    return extract_qa_from_blocks(blocks)


def extract_qa_from_blocks(blocks: list) -> list:
    """
    Extract Q&A pairs from Textract blocks.
    
    Strategies:
    1. KEY_VALUE_SET pairs (form fields)
    2. Table rows (question in col 1, answer in col 2+)
    3. Text pattern matching (numbered questions followed by answers)
    """
    qa_pairs = []

    # Strategy 1: Key-Value pairs from FORMS detection
    key_map = {}
    value_map = {}
    block_map = {b["Id"]: b for b in blocks}

    for block in blocks:
        if block["BlockType"] == "KEY_VALUE_SET":
            if "KEY" in block.get("EntityTypes", []):
                key_map[block["Id"]] = block
            elif "VALUE" in block.get("EntityTypes", []):
                value_map[block["Id"]] = block

    for key_id, key_block in key_map.items():
        key_text = get_text_from_block(key_block, block_map)
        # Find associated value
        for rel in key_block.get("Relationships", []):
            if rel["Type"] == "VALUE":
                for val_id in rel["Ids"]:
                    if val_id in value_map:
                        val_text = get_text_from_block(value_map[val_id], block_map)
                        if key_text and val_text and len(val_text) > 5:
                            qa_pairs.append({
                                "question_text": key_text.strip(),
                                "answer_text": val_text.strip(),
                                "extraction_method": "form_field",
                            })

    # Strategy 2: Table extraction
    tables = extract_tables(blocks, block_map)
    for table_data in tables:
        if len(table_data) > 1 and len(table_data[0]) >= 2:
            # Assume first column is question, second is answer
            for row in table_data[1:]:  # Skip header
                if len(row) >= 2 and row[0] and row[1] and len(row[1]) > 10:
                    qa_pairs.append({
                        "question_text": row[0].strip(),
                        "answer_text": row[1].strip(),
                        "extraction_method": "table",
                    })

    # Strategy 3: Text pattern matching (numbered questions)
    full_text = "\n".join(
        get_text_from_block(b, block_map)
        for b in blocks
        if b["BlockType"] == "LINE"
    )
    pattern_pairs = extract_qa_from_text(full_text)
    qa_pairs.extend(pattern_pairs)

    # Deduplicate
    seen = set()
    unique_pairs = []
    for pair in qa_pairs:
        key = (pair["question_text"][:50], pair["answer_text"][:50])
        if key not in seen:
            seen.add(key)
            unique_pairs.append(pair)

    logger.info(f"Extracted {len(unique_pairs)} unique Q&A pairs")
    return unique_pairs


def extract_qa_from_text(text: str) -> list:
    """Extract Q&A from plain text using pattern matching."""
    pairs = []

    # Pattern: numbered question followed by answer
    # e.g., "1. Do you encrypt data at rest?\nYes, we use AES-256..."
    lines = text.split("\n")
    i = 0
    while i < len(lines) - 1:
        line = lines[i].strip()
        # Check if line looks like a question
        if re.match(r"^(\d+[\.\)]\s*|Q[\.:]\s*)", line) and "?" in line:
            question = re.sub(r"^(\d+[\.\)]\s*|Q[\.:]\s*)", "", line).strip()
            # Collect answer lines until next question
            answer_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i].strip()
                if re.match(r"^(\d+[\.\)]\s*|Q[\.:]\s*)", next_line) and "?" in next_line:
                    break
                if next_line:
                    answer_lines.append(next_line)
                i += 1
            answer = " ".join(answer_lines).strip()
            if question and answer and len(answer) > 10:
                pairs.append({
                    "question_text": question,
                    "answer_text": answer,
                    "extraction_method": "text_pattern",
                })
        else:
            i += 1

    return pairs


def get_text_from_block(block: dict, block_map: dict) -> str:
    """Get text content from a block and its children."""
    text = ""
    if "Relationships" in block:
        for rel in block["Relationships"]:
            if rel["Type"] == "CHILD":
                for child_id in rel["Ids"]:
                    child = block_map.get(child_id, {})
                    if child.get("BlockType") == "WORD":
                        text += child.get("Text", "") + " "
                    elif child.get("BlockType") == "SELECTION_ELEMENT":
                        if child.get("SelectionStatus") == "SELECTED":
                            text += "[X] "
                        else:
                            text += "[ ] "
    return text.strip()


def extract_tables(blocks: list, block_map: dict) -> list:
    """Extract table data from Textract blocks."""
    tables = []

    for block in blocks:
        if block["BlockType"] == "TABLE":
            table_data = {}
            for rel in block.get("Relationships", []):
                if rel["Type"] == "CHILD":
                    for cell_id in rel["Ids"]:
                        cell = block_map.get(cell_id, {})
                        if cell.get("BlockType") == "CELL":
                            row = cell.get("RowIndex", 0)
                            col = cell.get("ColumnIndex", 0)
                            text = get_text_from_block(cell, block_map)
                            if row not in table_data:
                                table_data[row] = {}
                            table_data[row][col] = text

            # Convert to list of lists
            if table_data:
                max_row = max(table_data.keys())
                max_col = max(max(cols.keys()) for cols in table_data.values())
                table_list = []
                for r in range(1, max_row + 1):
                    row_data = []
                    for c in range(1, max_col + 1):
                        row_data.append(table_data.get(r, {}).get(c, ""))
                    table_list.append(row_data)
                tables.append(table_list)

    return tables


def store_draft_answers(qa_pairs: list, source_document: str) -> int:
    """Store extracted Q&A pairs as DRAFT in DynamoDB."""
    count = 0
    with table.batch_writer() as batch:
        for pair in qa_pairs:
            item = {
                "answer_id": str(uuid.uuid4()),
                "question_text": pair["question_text"][:2000],
                "answer_text": pair["answer_text"][:5000],
                "category": categorize_answer(pair["question_text"]),
                "source_framework": "EXTRACTED",
                "source_document": source_document,
                "extraction_method": pair.get("extraction_method", "unknown"),
                "status": "DRAFT",
                "extracted_date": datetime.utcnow().strftime("%Y-%m-%d"),
            }
            item = {k: v for k, v in item.items() if v}
            batch.put_item(Item=item)
            count += 1
    return count


def categorize_answer(question: str) -> str:
    """Auto-categorize based on question keywords."""
    q_lower = question.lower()
    categories = {
        "encryption": ["encrypt", "cryptograph", "key management", "tls", "ssl", "aes"],
        "access_control": ["access", "authentication", "mfa", "password", "identity", "sso"],
        "incident_response": ["incident", "breach", "response plan", "forensic"],
        "data_protection": ["data protect", "privacy", "pii", "retention", "disposal", "classification"],
        "network_security": ["network", "firewall", "segmentation", "vpn", "ids", "ips"],
        "vendor_management": ["vendor", "third-party", "supply chain", "subprocessor"],
        "business_continuity": ["continuity", "disaster recovery", "backup", "rto", "rpo"],
        "vulnerability_management": ["vulnerability", "patch", "scan", "penetration"],
        "governance": ["policy", "governance", "compliance", "audit", "risk management"],
        "training": ["training", "awareness", "phishing"],
    }

    for category, keywords in categories.items():
        if any(kw in q_lower for kw in keywords):
            return category
    return "general"


def notify(subject: str, message: str):
    """Send SNS notification if configured."""
    if SNS_TOPIC_ARN:
        try:
            sns.publish(TopicArn=SNS_TOPIC_ARN, Subject=subject[:100], Message=message)
        except Exception as e:
            logger.warning(f"SNS notification failed: {e}")
