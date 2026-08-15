"""
Re-index the Knowledge Base with trimmed text control files.

This is not necessary at the moment unless we switch to OpenSearch, right now DynamoDB is covering things
S3 Vectors has a 2048-byte metadata limit per record. The full SCF control
text (especially maturity criteria) exceeds this. We trim maturity criteria
to 200 chars per level and solutions to 200 chars per size tier.

WHAT'S TRIMMED:
- SCR-CMM maturity criteria: first 200 chars per level (full text is 500-3000 chars)
- Implementation solutions: first 200 chars per org size

WHAT'S KEPT IN FULL:
- Control ID, name, domain, description, control question
- Weight, conformity cadence, PPTDF applicability, NIST CSF function
- ERL references (evidence request list)
- All 14 key framework mappings (HIPAA, NIST, ISO, PCI, NIS2, etc.)
- Risk/threat summary

For full SCR-CMM maturity criteria, refer to:
https://securecontrolsframework.com/free-content/scf-download
"""
Lambda: scf-agent-scf-updater (Python 3.13, 5-min timeout)
Schedule: Every Monday at 8:00 UTC (ENABLED)
SSM Parameter: Tracks current version (2026.2)
import json
import os

import boto3

BUCKET = "scf-agent-scf-data-339712707840-us-east-1"
KB_ID = "7Z1IJYUGD8"
DS_ID = "WGIGWDAIJZ"
REGION = "us-east-1"
SCF_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "SCF-2026-2", "JSON", "scf-full-2026.2.json"
)

MAX_CMM_CHARS = 200
MAX_SOLUTION_CHARS = 200


def main():
    s3 = boto3.client("s3", region_name=REGION)

    # Step 1: Clear the bucket
    print("Clearing existing S3 data...")
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=BUCKET):
        for obj in page.get("Contents", []):
            s3.delete_object(Bucket=BUCKET, Key=obj["Key"])
    print("  Bucket cleared.")

    # Step 2: Load SCF JSON
    print(f"Loading SCF JSON from: {SCF_PATH}")
    with open(SCF_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    print(
        f"  Loaded {data['metadata']['control_count']} controls, "
        f"{data['metadata']['domain_count']} domains"
    )

    # Step 3: Upload each control as a trimmed text file
    print("Uploading controls as trimmed text files...")
    count = 0
    for ctrl in data["controls"]:
        text_parts = []
        text_parts.append(f"SCF Control: {ctrl['scf_id']} - {ctrl['scf_control_name']}")
        text_parts.append(f"Domain: {ctrl['scf_domain']}")
        text_parts.append(f"Description: {ctrl['description']}")
        text_parts.append(f"Control Question: {ctrl['control_question']}")
        text_parts.append(f"Weight: {ctrl['weight']}")
        text_parts.append(f"Conformity Cadence: {ctrl['conformity_cadence']}")
        text_parts.append(f"PPTDF Applicability: {ctrl['pptdf_applicability']}")
        text_parts.append(f"NIST CSF Function: {ctrl['nist_csf_function_grouping']}")
        text_parts.append(f"ERL Reference: {ctrl.get('erl_reference', 'N/A')}")
        text_parts.append("")

        # Maturity levels (trimmed)
        cmm = ctrl.get("cmm_levels", {})
        if cmm:
            text_parts.append("Maturity Levels (summarized - see SCF download for full criteria):")
            for level, criteria in cmm.items():
                short_level = level.replace("SCR-CMM ", "")
                trimmed = criteria[:MAX_CMM_CHARS]
                if len(criteria) > MAX_CMM_CHARS:
                    trimmed += "..."
                text_parts.append(f"  {short_level}: {trimmed}")
            text_parts.append("")

        # Key framework mappings (full)
        mappings = ctrl.get("mappings", {})
        key_frameworks = [
            "NIST 800-53 R5",
            "NIST CSF 2.0",
            "NIST 800-171 R3",
            "ISO 27001 2022",
            "ISO 27002 2022",
            "PCI DSS 4.0.1",
            "US HIPAA Security Rule / NIST SP 800-66 R2",
            "US HIPAA Administrative Simplification 2013",
            "AICPA TSC 2017:2022 (used for SOC 2)",
            "EMEA EU NIS2 2022",
            "EMEA EU DORA 2023",
            "EMEA EU AI Act",
            "US - NY DFS 23 NYCRR500 2023 Amd 2",
            "US FedRAMP R5 (moderate)",
        ]
        mapping_lines = []
        for fw in key_frameworks:
            if fw in mappings and mappings[fw]:
                mapping_lines.append(f"  {fw}: {mappings[fw]}")
        if mapping_lines:
            text_parts.append("Framework Mappings:")
            text_parts.extend(mapping_lines)
            text_parts.append("")

        # Risk/threat
        if mappings.get("Risk Threat Summary"):
            text_parts.append(f"Risk Threats: {mappings['Risk Threat Summary']}")
            text_parts.append("")

        # Solutions (trimmed)
        extra = ctrl.get("extra", {})
        solution_added = False
        for key, val in extra.items():
            if "Possible Solutions" in key and val:
                if not solution_added:
                    text_parts.append("Implementation Solutions:")
                    solution_added = True
                size_label = (
                    key.replace("Possible Solutions & Considerations ", "")
                    if "Possible Solutions" in key
                    else key
                )
                trimmed = val[:MAX_SOLUTION_CHARS]
                if len(val) > MAX_SOLUTION_CHARS:
                    trimmed += "..."
                text_parts.append(f"  {size_label}: {trimmed}")
        if solution_added:
            text_parts.append("")

        text_content = "\n".join(text_parts)

        key = f"controls/{ctrl['scf_id']}.txt"
        s3.put_object(
            Bucket=BUCKET,
            Key=key,
            Body=text_content.encode("utf-8"),
            ContentType="text/plain",
        )
        count += 1
        if count % 200 == 0:
            print(f"  Uploaded {count} controls...")

    print(f"  Done: {count} control files uploaded.")

    # Step 4: Upload domain summary
    domain_text = "SCF 2026.2 - All Domains Summary\n\n"
    for d in data["domains"]:
        domain_text += (
            f"Domain {d['number']}: {d['identifier']} - {d['name']} "
            f"({d['control_count']} controls)\n"
        )
        domain_text += f"  Principles: {d['principles']}\n"
        domain_text += f"  Intent: {d['intent']}\n\n"
    s3.put_object(
        Bucket=BUCKET,
        Key="controls/00-DOMAINS-SUMMARY.txt",
        Body=domain_text.encode("utf-8"),
        ContentType="text/plain",
    )
    print("  Domain summary uploaded.")

    # Step 5: Trigger KB ingestion
    print(f"\nTriggering Knowledge Base ingestion (KB: {KB_ID}, DS: {DS_ID})...")
    bedrock = boto3.client("bedrock-agent", region_name=REGION)
    response = bedrock.start_ingestion_job(knowledgeBaseId=KB_ID, dataSourceId=DS_ID)
    job_id = response["ingestionJob"]["ingestionJobId"]
    print(f"  Ingestion job started: {job_id}")
    print(
        f"  Monitor: aws bedrock-agent get-ingestion-job "
        f"--knowledge-base-id {KB_ID} --data-source-id {DS_ID} "
        f"--ingestion-job-id {job_id} --region {REGION}"
    )
    print(f"\n  NOTE: Maturity criteria trimmed to {MAX_CMM_CHARS} chars/level.")
    print("  For full SCR-CMM criteria: https://securecontrolsframework.com/free-content/scf-download")


if __name__ == "__main__":
    main()
