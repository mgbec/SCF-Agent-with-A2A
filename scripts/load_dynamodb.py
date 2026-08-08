"""
Load full SCF control data into DynamoDB.

Each control is stored as a complete item with ALL data:
- Full maturity criteria (all levels, untruncated)
- All 252+ framework mappings
- Complete solutions text
- Risk/threat correlations
- ERL references

Usage:
    python load_dynamodb.py
"""

import json
import os
import subprocess
import sys
from decimal import Decimal

import boto3


def get_terraform_output(key: str) -> str:
    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    result = subprocess.run(
        ["terraform", "output", "-raw", key],
        cwd=tf_dir, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main():
    table_name = get_terraform_output("dynamodb_table_name")
    if not table_name:
        # Fallback
        table_name = "scf-agent-scf-controls"
        print(f"  Using fallback table name: {table_name}")

    region = "us-east-1"
    scf_path = os.path.join(
        os.path.dirname(__file__), "..", "..", "SCF-2026-2", "JSON", "scf-full-2026.2.json"
    )

    print(f"Loading SCF JSON from: {scf_path}")
    with open(scf_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(f"  {data['metadata']['control_count']} controls, {data['metadata']['domain_count']} domains")

    dynamodb = boto3.resource("dynamodb", region_name=region)
    table = dynamodb.Table(table_name)

    print(f"\nLoading into DynamoDB table: {table_name}")
    count = 0

    with table.batch_writer() as batch:
        for ctrl in data["controls"]:
            item = {
                "scf_id": ctrl["scf_id"],
                "domain_id": ctrl["scf_id"].split("-")[0],
                "scf_domain": ctrl["scf_domain"],
                "scf_control_name": ctrl["scf_control_name"],
                "description": ctrl["description"],
                "control_question": ctrl["control_question"],
                "conformity_cadence": ctrl["conformity_cadence"],
                "erl_reference": ctrl.get("erl_reference", ""),
                "weight": ctrl["weight"],
                "pptdf_applicability": ctrl["pptdf_applicability"],
                "nist_csf_function_grouping": ctrl["nist_csf_function_grouping"],
                "cmm_levels": ctrl.get("cmm_levels", {}),
                "mappings": ctrl.get("mappings", {}),
                "extra": ctrl.get("extra", {}),
            }

            # DynamoDB doesn't allow empty strings in sets
            item = _clean_empty_strings(item)

            batch.put_item(Item=item)
            count += 1
            if count % 200 == 0:
                print(f"  Loaded {count} controls...")

    print(f"\n✅ Done: {count} controls loaded into DynamoDB.")
    print(f"   Table: {table_name}")
    print(f"   Region: {region}")


def _clean_empty_strings(obj):
    """DynamoDB doesn't allow empty strings. Replace with None or remove."""
    if isinstance(obj, dict):
        return {k: _clean_empty_strings(v) for k, v in obj.items() if v != ""}
    elif isinstance(obj, list):
        return [_clean_empty_strings(item) for item in obj]
    return obj


if __name__ == "__main__":
    main()
