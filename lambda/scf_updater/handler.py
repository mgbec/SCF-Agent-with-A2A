"""
SCF Auto-Updater Lambda

Runs weekly via EventBridge. Checks the SCF download endpoint for a new version,
compares against the version stored in SSM Parameter Store, and if newer:
1. Downloads the full SCF JSON
2. Uploads to S3 (full file + per-domain chunks)
3. Triggers Bedrock Knowledge Base re-ingestion
4. Updates the SSM parameter with the new version
5. Sends SNS notification

If no new version, exits silently (no notification noise).
"""

import json
import logging
import os
import urllib.request
from typing import Optional

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Environment variables
SCF_DATA_BUCKET = os.environ["SCF_DATA_BUCKET"]
KNOWLEDGE_BASE_ID = os.environ["KNOWLEDGE_BASE_ID"]
SNS_TOPIC_ARN = os.environ["SNS_TOPIC_ARN"]
VERSION_PARAM = os.environ["VERSION_PARAM"]
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "")
SCF_DOWNLOAD_URL = os.environ.get(
    "SCF_DOWNLOAD_URL",
    "https://content.securecontrolsframework.com/json/scf-full.json",
)

s3 = boto3.client("s3")
ssm = boto3.client("ssm")
sns = boto3.client("sns")
bedrock_agent = boto3.client("bedrock-agent")


def get_current_version() -> str:
    """Get the currently deployed SCF version from SSM."""
    try:
        response = ssm.get_parameter(Name=VERSION_PARAM)
        return response["Parameter"]["Value"]
    except ssm.exceptions.ParameterNotFound:
        return "0.0"


def set_current_version(version: str) -> None:
    """Update the deployed SCF version in SSM."""
    ssm.put_parameter(Name=VERSION_PARAM, Value=version, Overwrite=True)


def download_scf_json() -> Optional[dict]:
    """Download the latest SCF JSON from the SCF website."""
    logger.info(f"Downloading SCF JSON from: {SCF_DOWNLOAD_URL}")
    try:
        req = urllib.request.Request(
            SCF_DOWNLOAD_URL,
            headers={"User-Agent": "SCF-Compliance-Agent-Updater/1.0"},
        )
        with urllib.request.urlopen(req, timeout=120) as response:
            data = json.loads(response.read().decode("utf-8"))
            logger.info(f"Downloaded SCF version: {data['metadata']['version']}")
            return data
    except Exception as e:
        logger.error(f"Failed to download SCF JSON: {e}")
        return None


def upload_to_s3(scf_data: dict) -> None:
    """Upload SCF data to S3 in multiple formats for optimal KB indexing."""
    version = scf_data["metadata"]["version"]

    # 1. Upload the full JSON
    logger.info("Uploading full SCF JSON...")
    s3.put_object(
        Bucket=SCF_DATA_BUCKET,
        Key="scf-full-current.json",
        Body=json.dumps(scf_data, indent=2).encode("utf-8"),
        ContentType="application/json",
        Metadata={"scf-version": version},
    )

    # Also keep a versioned copy for rollback
    s3.put_object(
        Bucket=SCF_DATA_BUCKET,
        Key=f"versions/scf-full-{version}.json",
        Body=json.dumps(scf_data, indent=2).encode("utf-8"),
        ContentType="application/json",
        Metadata={"scf-version": version},
    )

    # 2. Upload per-domain files for better Knowledge Base chunking
    logger.info("Uploading per-domain control files...")
    controls_by_domain = {}
    for ctrl in scf_data["controls"]:
        domain_id = ctrl["scf_id"].split("-")[0]
        if domain_id not in controls_by_domain:
            controls_by_domain[domain_id] = []
        controls_by_domain[domain_id].append(ctrl)

    for domain_id, controls in controls_by_domain.items():
        domain_info = next(
            (d for d in scf_data["domains"] if d["identifier"] == domain_id),
            {"name": domain_id, "identifier": domain_id},
        )
        domain_doc = {
            "metadata": {"scf_version": version, "domain": domain_id},
            "domain": domain_info,
            "controls": controls,
        }
        s3.put_object(
            Bucket=SCF_DATA_BUCKET,
            Key=f"domains/{domain_id}-controls.json",
            Body=json.dumps(domain_doc, indent=2).encode("utf-8"),
            ContentType="application/json",
        )

    # 3. Upload framework mapping index
    logger.info("Building framework mapping index...")
    framework_index = {}
    for ctrl in scf_data["controls"]:
        for key, value in ctrl.get("mappings", {}).items():
            if value and not key.startswith("Risk ") and not key.startswith("Threat "):
                if key not in framework_index:
                    framework_index[key] = []
                framework_index[key].append(
                    {"scf_id": ctrl["scf_id"], "references": value}
                )

    s3.put_object(
        Bucket=SCF_DATA_BUCKET,
        Key="framework-mapping-index.json",
        Body=json.dumps(framework_index, indent=2).encode("utf-8"),
        ContentType="application/json",
    )

    logger.info(
        f"Upload complete: {len(scf_data['controls'])} controls, "
        f"{len(controls_by_domain)} domains, {len(framework_index)} frameworks"
    )


def trigger_kb_sync() -> None:
    """Trigger Bedrock Knowledge Base data source re-ingestion."""
    logger.info(f"Triggering KB sync for: {KNOWLEDGE_BASE_ID}")
    try:
        ds_response = bedrock_agent.list_data_sources(knowledgeBaseId=KNOWLEDGE_BASE_ID)
        for ds in ds_response.get("dataSourceSummaries", []):
            ds_id = ds["dataSourceId"]
            bedrock_agent.start_ingestion_job(
                knowledgeBaseId=KNOWLEDGE_BASE_ID, dataSourceId=ds_id
            )
            logger.info(f"Ingestion job started for data source: {ds_id}")
    except Exception as e:
        logger.error(f"Failed to trigger KB sync: {e}")
        raise


def reload_dynamodb(scf_data: dict) -> None:
    """Reload all controls into DynamoDB with full untruncated data."""
    if not DYNAMODB_TABLE:
        logger.warning("DYNAMODB_TABLE not set, skipping DynamoDB reload")
        return

    logger.info(f"Reloading DynamoDB table: {DYNAMODB_TABLE}")
    dynamodb = boto3.resource("dynamodb")
    table = dynamodb.Table(DYNAMODB_TABLE)

    count = 0
    with table.batch_writer() as batch:
        for ctrl in scf_data["controls"]:
            item = {
                "scf_id": ctrl["scf_id"],
                "domain_id": ctrl["scf_id"].split("-")[0],
                "scf_domain": ctrl["scf_domain"],
                "scf_control_name": ctrl["scf_control_name"],
                "description": ctrl["description"],
                "control_question": ctrl["control_question"],
                "conformity_cadence": ctrl["conformity_cadence"],
                "erl_reference": ctrl.get("erl_reference", "N/A"),
                "weight": ctrl["weight"],
                "pptdf_applicability": ctrl["pptdf_applicability"],
                "nist_csf_function_grouping": ctrl["nist_csf_function_grouping"],
                "cmm_levels": ctrl.get("cmm_levels", {}),
                "mappings": ctrl.get("mappings", {}),
                "extra": ctrl.get("extra", {}),
            }
            # DynamoDB doesn't allow empty strings
            item = {k: v for k, v in item.items() if v != ""}
            batch.put_item(Item=item)
            count += 1

    logger.info(f"DynamoDB reload complete: {count} controls loaded")


def send_notification(subject: str, message: str) -> None:
    """Send SNS notification."""
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject[:100],
        Message=message,
    )


def lambda_handler(event, context):
    """
    Main handler. Checks for new SCF version and updates if found.
    """
    logger.info("SCF Updater triggered")

    current_version = get_current_version()
    logger.info(f"Current deployed version: {current_version}")

    # Download latest SCF JSON
    scf_data = download_scf_json()
    if not scf_data:
        send_notification(
            subject="[SCF Agent] Update check FAILED",
            message=(
                "The SCF auto-updater failed to download the latest SCF JSON.\n"
                f"URL: {SCF_DOWNLOAD_URL}\n"
                "Please check the Lambda logs and verify the download URL is still valid."
            ),
        )
        return {"statusCode": 500, "body": "Download failed"}

    new_version = scf_data["metadata"]["version"]
    control_count = scf_data["metadata"]["control_count"]
    domain_count = scf_data["metadata"]["domain_count"]

    # Compare versions
    if new_version == current_version:
        logger.info(f"No update needed. Current version {current_version} is latest.")
        return {
            "statusCode": 200,
            "body": f"No update. Current version: {current_version}",
        }

    # New version detected - update everything
    logger.info(f"NEW VERSION DETECTED: {current_version} → {new_version}")

    try:
        # Upload to S3
        upload_to_s3(scf_data)

        # Reload DynamoDB with full control data
        reload_dynamodb(scf_data)

        # Trigger Knowledge Base re-ingestion
        trigger_kb_sync()

        # Update version tracker
        set_current_version(new_version)

        # Notify team
        send_notification(
            subject=f"[SCF Agent] Updated to SCF {new_version}",
            message=(
                f"The SCF Compliance Agent knowledge base has been updated.\n\n"
                f"Previous version: {current_version}\n"
                f"New version: {new_version}\n"
                f"Controls: {control_count}\n"
                f"Domains: {domain_count}\n\n"
                f"Changes:\n"
                f"- Full JSON uploaded to s3://{SCF_DATA_BUCKET}/scf-full-current.json\n"
                f"- Versioned copy at s3://{SCF_DATA_BUCKET}/versions/scf-full-{new_version}.json\n"
                f"- Per-domain files updated in s3://{SCF_DATA_BUCKET}/domains/\n"
                f"- Framework mapping index rebuilt\n"
                f"- DynamoDB table reloaded with all controls\n"
                f"- Bedrock Knowledge Base re-ingestion triggered\n\n"
                f"Action required:\n"
                f"- Review the SCF errata/changelog for breaking changes\n"
                f"- Verify KB sync completes successfully in the console\n"
                f"- Consider re-running active assessments against new version"
            ),
        )

        logger.info(f"Update complete: {current_version} → {new_version}")
        return {
            "statusCode": 200,
            "body": f"Updated from {current_version} to {new_version}",
        }

    except Exception as e:
        logger.error(f"Update failed: {e}", exc_info=True)
        send_notification(
            subject=f"[SCF Agent] Update FAILED ({current_version} → {new_version})",
            message=(
                f"The SCF auto-updater detected version {new_version} but failed during update.\n\n"
                f"Error: {str(e)}\n\n"
                f"The agent is still running on version {current_version}.\n"
                f"Please check the Lambda logs and retry manually if needed."
            ),
        )
        return {"statusCode": 500, "body": f"Update failed: {e}"}
