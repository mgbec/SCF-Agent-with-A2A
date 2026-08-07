"""
Test the deployed SCF Compliance Agent via AgentCore Runtime.

Usage:
    cd scripts/
    python test_agent.py
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


def invoke_agent(agent_arn: str, prompt: str, session_id: str = "test-session") -> dict:
    """Invoke the agent via the AgentCore Runtime API."""
    client = boto3.client("bedrock-agentcore", region_name="us-east-1")

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agent_arn,
        payload=json.dumps({
            "prompt": prompt,
            "session_id": session_id,
        }),
    )

    return json.loads(response["body"].read().decode("utf-8"))


def main():
    print("=" * 60)
    print("SCF Compliance Agent - Integration Tests")
    print("=" * 60)

    agent_arn = get_terraform_output("agent_runtime_arn")
    print(f"\nAgent ARN: {agent_arn}\n")

    test_cases = [
        {
            "name": "Control Lookup",
            "prompt": "Look up SCF control GOV-01 and tell me what it covers.",
        },
        {
            "name": "Domain Listing",
            "prompt": "List all SCF domains and their control counts.",
        },
        {
            "name": "Framework Mapping",
            "prompt": "What SCF controls map to HIPAA Security Rule requirements?",
        },
        {
            "name": "Maturity Assessment",
            "prompt": (
                "What does maturity Level 3 (Well Defined) look like for "
                "access control (IAC domain)?"
            ),
        },
        {
            "name": "Gap Analysis",
            "prompt": (
                "We're a medium-sized healthcare company that has implemented "
                "GOV-01, GOV-02, IAC-01, IAC-06, IAC-15, NET-01, CRY-01. "
                "What gaps do we have for HIPAA compliance?"
            ),
        },
        {
            "name": "Compliance Scoping",
            "prompt": "What controls are required for SCF ESP Level 1 Foundational profile?",
        },
    ]

    results = []
    for i, tc in enumerate(test_cases, 1):
        print(f"\n{'─' * 60}")
        print(f"Test {i}/{len(test_cases)}: {tc['name']}")
        print(f"Prompt: {tc['prompt'][:80]}...")
        print(f"{'─' * 60}")

        try:
            response = invoke_agent(agent_arn, tc["prompt"])
            status = response.get("statusCode", "unknown")
            body = response.get("body", {})

            if status == 200:
                print(f"✓ PASS - Response received ({len(str(body))} chars)")
                print(f"  Preview: {str(body.get('response', ''))[:200]}...")
                results.append(("PASS", tc["name"]))
            else:
                print(f"✗ FAIL - Status: {status}")
                print(f"  Error: {body.get('error', 'unknown')}")
                results.append(("FAIL", tc["name"]))
        except Exception as e:
            print(f"✗ ERROR - {e}")
            results.append(("ERROR", tc["name"]))

    # Summary
    print(f"\n{'=' * 60}")
    print("RESULTS SUMMARY")
    print(f"{'=' * 60}")
    for status, name in results:
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} {status:5s} | {name}")

    passed = sum(1 for s, _ in results if s == "PASS")
    print(f"\n{passed}/{len(results)} tests passed")

    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
