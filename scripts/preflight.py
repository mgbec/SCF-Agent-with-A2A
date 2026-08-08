"""
Preflight check - run BEFORE deploying to catch model/permission issues early.

Validates:
1. AWS credentials are configured
2. The model ID is valid and invocable (not legacy, not wrong format)
3. The Knowledge Base is accessible
4. Required permissions exist

Usage:
    python preflight.py
    python preflight.py --model us.anthropic.claude-sonnet-4-6
"""

import argparse
import json
import os
import subprocess
import sys

import boto3
from botocore.exceptions import ClientError


def check_credentials():
    """Verify AWS credentials are configured."""
    print("  Checking AWS credentials...", end=" ")
    try:
        sts = boto3.client("sts")
        identity = sts.get_caller_identity()
        print(f"✓ ({identity['Arn']})")
        return True
    except Exception as e:
        print(f"✗ {e}")
        return False


def check_model(model_id: str, region: str):
    """Test that the model can actually be invoked."""
    print(f"  Testing model invocation: {model_id}...", end=" ")
    try:
        bedrock = boto3.client("bedrock-runtime", region_name=region)
        response = bedrock.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": "Say hello in one word."}]}],
            inferenceConfig={"maxTokens": 10},
        )
        output = response["output"]["message"]["content"][0]["text"]
        print(f"✓ (response: '{output.strip()}')")
        return True
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"✗")
        print(f"    Error: {error_code}: {error_msg}")

        # Common fixes
        if "on-demand throughput isn't supported" in error_msg:
            print(f"    FIX: Use an inference profile ID (e.g., 'us.{model_id}') instead of the raw model ID")
            # Try to suggest the correct one
            try:
                bedrock_ctrl = boto3.client("bedrock", region_name=region)
                profiles = bedrock_ctrl.list_inference_profiles()
                matches = [
                    p["inferenceProfileId"]
                    for p in profiles.get("inferenceProfileSummaries", [])
                    if model_id.split(".")[-1].split("-")[0] in p["inferenceProfileId"]
                ]
                if matches:
                    print(f"    Available profiles: {matches[:5]}")
            except Exception:
                pass
        elif "ResourceNotFoundException" in error_code:
            print(f"    FIX: Model is legacy/deprecated. Use a current inference profile.")
        elif "AccessDeniedException" in error_code:
            print(f"    FIX: Enable model access in Bedrock console, or check IAM permissions.")
        elif "ValidationException" in error_code and "not found" in error_msg.lower():
            print(f"    FIX: Model ID doesn't exist. Check spelling or use 'aws bedrock list-inference-profiles'")
        return False


def check_knowledge_base(kb_id: str, region: str):
    """Test that the Knowledge Base is accessible and has data."""
    print(f"  Testing Knowledge Base: {kb_id}...", end=" ")
    try:
        client = boto3.client("bedrock-agent-runtime", region_name=region)
        response = client.retrieve(
            knowledgeBaseId=kb_id,
            retrievalQuery={"text": "SCF governance control"},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 1}},
        )
        results = response.get("retrievalResults", [])
        if results:
            print(f"✓ ({len(results)} result(s), KB has data)")
            return True
        else:
            print(f"⚠ KB accessible but returned no results. Has data been ingested?")
            return False
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        error_msg = e.response["Error"]["Message"]
        print(f"✗")
        print(f"    Error: {error_code}: {error_msg}")
        if "AccessDeniedException" in error_code:
            print(f"    FIX: Add bedrock:Retrieve permission for KB ARN to your role")
        elif "ResourceNotFoundException" in error_code:
            print(f"    FIX: KB ID '{kb_id}' doesn't exist. Check terraform output knowledge_base_id")
        return False


def check_ecr_image(repo_name: str, region: str):
    """Check if the ECR repo has an image tagged 'latest'."""
    print(f"  Checking ECR image: {repo_name}:latest...", end=" ")
    try:
        ecr = boto3.client("ecr", region_name=region)
        response = ecr.describe_images(
            repositoryName=repo_name,
            imageIds=[{"imageTag": "latest"}],
        )
        images = response.get("imageDetails", [])
        if images:
            pushed = images[0].get("imagePushedAt", "unknown")
            print(f"✓ (pushed: {pushed})")
            return True
        else:
            print(f"✗ No 'latest' tag found")
            return False
    except ClientError as e:
        if "ImageNotFoundException" in str(e):
            print(f"✗ No image with tag 'latest'. Build and push the container first.")
        else:
            print(f"✗ {e}")
        return False


def get_terraform_output(key: str) -> str:
    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    result = subprocess.run(
        ["terraform", "output", "-raw", key],
        cwd=tf_dir, capture_output=True, text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def main():
    parser = argparse.ArgumentParser(description="Preflight check for SCF Compliance Agent")
    parser.add_argument("--model", default="", help="Model ID to test (overrides tfvars)")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args()

    print("=" * 60)
    print("SCF Compliance Agent - Preflight Check")
    print("=" * 60)
    print()

    results = []

    # 1. Credentials
    results.append(("AWS Credentials", check_credentials()))

    # 2. Model
    model_id = args.model
    if not model_id:
        # Try to get from terraform
        model_id = get_terraform_output("bedrock_model_id") if not model_id else model_id
    if not model_id:
        # Read from tfvars
        tfvars_path = os.path.join(os.path.dirname(__file__), "..", "terraform", "terraform.tfvars")
        if os.path.exists(tfvars_path):
            with open(tfvars_path) as f:
                for line in f:
                    if "bedrock_model_id" in line and "=" in line:
                        model_id = line.split("=")[1].strip().strip('"')
    if not model_id:
        model_id = "us.anthropic.claude-sonnet-4-6"

    results.append(("Model Invocation", check_model(model_id, args.region)))

    # 3. Knowledge Base
    kb_id = get_terraform_output("knowledge_base_id")
    if kb_id:
        results.append(("Knowledge Base", check_knowledge_base(kb_id, args.region)))
    else:
        print("  Knowledge Base: ⚠ skipped (no terraform output found)")

    # 4. ECR Image
    results.append(("ECR Image", check_ecr_image("scf-agent-compliance-agent", args.region)))

    # Summary
    print()
    print("=" * 60)
    print("RESULTS")
    print("=" * 60)
    all_passed = True
    for name, passed in results:
        icon = "✓" if passed else "✗"
        print(f"  {icon} {name}")
        if not passed:
            all_passed = False

    print()
    if all_passed:
        print("All checks passed. Ready to deploy/invoke.")
    else:
        print("Some checks failed. Fix the issues above before deploying.")

    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
