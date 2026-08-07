"""
Upload SCF 2026.2 JSON data to S3 for the Bedrock Knowledge Base.

This script:
1. Reads the SCF JSON from the local SCF-2026-2 distribution
2. Uploads it to the S3 bucket created by Terraform
3. Optionally triggers a Knowledge Base sync

Usage:
    cd scripts/
    python upload_scf_data.py
"""

import json
import os
import subprocess
import sys

import boto3


def get_terraform_output(key: str) -> str:
    """Get a value from terraform outputs."""
    result = subprocess.run(
        ["terraform", "output", "-raw", key],
        cwd=os.path.join(os.path.dirname(__file__), "..", "terraform"),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get terraform output '{key}': {result.stderr}")
    return result.stdout.strip()


def upload_scf_data():
    """Upload the SCF JSON to S3."""
    # Get terraform outputs
    print("Getting terraform outputs...")
    bucket_name = get_terraform_output("scf_data_bucket")
    kb_id = get_terraform_output("knowledge_base_id")
    print(f"  Bucket: {bucket_name}")
    print(f"  Knowledge Base ID: {kb_id}")

    # Find the SCF JSON file
    scf_json_path = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "SCF-2026-2", "JSON", "scf-full-2026.2.json"
    )
    scf_json_path = os.path.abspath(scf_json_path)

    if not os.path.exists(scf_json_path):
        print(f"ERROR: SCF JSON not found at: {scf_json_path}")
        print("Please ensure the SCF-2026-2 data is in the expected location.")
        sys.exit(1)

    print(f"\nLoading SCF JSON from: {scf_json_path}")
    with open(scf_json_path, "r", encoding="utf-8") as f:
        scf_data = json.load(f)

    print(f"  Version: {scf_data['metadata']['version']}")
    print(f"  Controls: {scf_data['metadata']['control_count']}")
    print(f"  Domains: {scf_data['metadata']['domain_count']}")

    # Upload the full JSON
    s3 = boto3.client("s3")

    print(f"\nUploading scf-full-2026.2.json to s3://{bucket_name}/...")
    s3.put_object(
        Bucket=bucket_name,
        Key="scf-full-2026.2.json",
        Body=json.dumps(scf_data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print("  Uploaded full SCF JSON.")

    # Also upload individual domain files for better KB chunking
    print("\nUploading per-domain control files for Knowledge Base chunking...")
    controls_by_domain = {}
    for ctrl in scf_data["controls"]:
        domain_id = ctrl["scf_id"].split("-")[0]
        if domain_id not in controls_by_domain:
            controls_by_domain[domain_id] = []
        controls_by_domain[domain_id].append(ctrl)

    for domain_id, controls in controls_by_domain.items():
        domain_info = next(
            (d for d in scf_data["domains"] if d["identifier"] == domain_id),
            {"name": domain_id, "identifier": domain_id}
        )
        domain_doc = {
            "domain": domain_info,
            "controls": controls,
        }
        key = f"domains/{domain_id}-controls.json"
        s3.put_object(
            Bucket=bucket_name,
            Key=key,
            Body=json.dumps(domain_doc, indent=2).encode("utf-8"),
            ContentType="application/json",
        )
        print(f"  Uploaded {key} ({len(controls)} controls)")

    # Upload a frameworks mapping index
    print("\nBuilding and uploading framework mapping index...")
    framework_index = {}
    for ctrl in scf_data["controls"]:
        for key, value in ctrl.get("mappings", {}).items():
            if value and not key.startswith("Risk ") and not key.startswith("Threat "):
                if key not in framework_index:
                    framework_index[key] = []
                framework_index[key].append({
                    "scf_id": ctrl["scf_id"],
                    "references": value,
                })

    s3.put_object(
        Bucket=bucket_name,
        Key="framework-mapping-index.json",
        Body=json.dumps(framework_index, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"  Uploaded framework-mapping-index.json ({len(framework_index)} frameworks)")

    # Trigger Knowledge Base sync
    print(f"\nTriggering Knowledge Base sync (ID: {kb_id})...")
    try:
        bedrock_agent = boto3.client("bedrock-agent")
        ds_response = bedrock_agent.list_data_sources(knowledgeBaseId=kb_id)
        for ds in ds_response.get("dataSourceSummaries", []):
            ds_id = ds["dataSourceId"]
            print(f"  Starting ingestion for data source: {ds_id}")
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=kb_id,
                dataSourceId=ds_id,
            )
            print(f"  Ingestion job started for {ds_id}")
    except Exception as e:
        print(f"  Warning: Could not trigger KB sync: {e}")
        print("  You can manually sync from the AWS Console.")

    print("\n✓ SCF data upload complete!")


if __name__ == "__main__":
    upload_scf_data()
