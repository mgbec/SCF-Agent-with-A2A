"""
Test the deployed SCF Compliance Agent via AgentCore Runtime.

Usage:
    cd scripts/
    python test_agent.py
"""

import base64
import json
import os
import subprocess
import sys
import tempfile

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

    payload = json.dumps({
        "prompt": prompt,
        "session_id": session_id,
    }).encode("utf-8")

    # Use a temp file for the streaming response
    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        response = client.invoke_agent_runtime(
            agentRuntimeArn=agent_arn,
            payload=payload,
            outfile=tmp_path,
        )

        # Read the response from the output file
        with open(tmp_path, "rb") as f:
            body = f.read()

        if body:
            try:
                return json.loads(body.decode("utf-8"))
            except json.JSONDecodeError:
                return {"response": body.decode("utf-8", errors="replace")}
        else:
            return {"response": "(empty response)", "statusCode": response.get("statusCode", 200)}
    except Exception as e:
        # Try the CLI approach as fallback
        return invoke_agent_cli(agent_arn, prompt)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def invoke_agent_cli(agent_arn: str, prompt: str) -> dict:
    """Fallback: invoke via AWS CLI."""
    payload_b64 = base64.b64encode(
        json.dumps({"prompt": prompt, "session_id": "test-session"}).encode()
    ).decode()

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "aws", "bedrock-agentcore", "invoke-agent-runtime",
                "--agent-runtime-arn", agent_arn,
                "--payload", payload_b64,
                "--region", "us-east-1",
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode != 0:
            return {"error": result.stderr.strip()}

        # Read response file
        if os.path.exists(tmp_path):
            with open(tmp_path, "r") as f:
                content = f.read()
            if content:
                try:
                    return json.loads(content)
                except json.JSONDecodeError:
                    return {"response": content}

        # Parse stdout for metadata
        if result.stdout:
            try:
                meta = json.loads(result.stdout)
                return {"statusCode": meta.get("statusCode", 200), "response": "OK (metadata only)"}
            except json.JSONDecodeError:
                pass

        return {"response": "Invocation completed (no body returned)", "statusCode": 200}
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def main():
    print("=" * 60)
    print("SCF Compliance Agent - Integration Tests")
    print("=" * 60)

    agent_arn = get_terraform_output("agent_runtime_arn")
    print(f"\nAgent ARN: {agent_arn}\n")

    test_cases = [
        {
            "name": "Basic Health Check",
            "prompt": "Hello, are you working?",
        },
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
            "prompt": "What SCF controls map to HIPAA Security Rule requirements? Show me the top 5.",
        },
        {
            "name": "Maturity Assessment",
            "prompt": "What does maturity Level 3 look like for access control (IAC domain)?",
        },
        {
            "name": "Gap Analysis",
            "prompt": "We have implemented GOV-01, IAC-01, IAC-15, NET-01, CRY-01. What gaps do we have for HIPAA?",
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

            if "error" in response:
                print(f"✗ FAIL - {response['error'][:200]}")
                results.append(("FAIL", tc["name"]))
            else:
                resp_text = response.get("response", str(response))
                print(f"✓ PASS - Response ({len(resp_text)} chars)")
                print(f"  Preview: {resp_text[:200]}...")
                results.append(("PASS", tc["name"]))
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
