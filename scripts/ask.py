"""
CLI interface for the SCF Compliance Agent.

Usage:
    python ask.py "What controls map to HIPAA?"
    python ask.py --interactive
    echo "List SCF domains" | python ask.py

Examples:
    python ask.py "Look up SCF control GOV-01"
    python ask.py "What gaps do we have for NIS2 if we have GOV-01,IAC-01,NET-01?"
    python ask.py "Generate an evidence checklist for IAC domain"
    python ask.py --interactive
"""

import base64
import json
import os
import subprocess
import sys
import tempfile


# Configuration
AGENT_ARN = None  # Will be populated from terraform output
REGION = "us-east-1"


def get_agent_arn():
    """Get the agent ARN from terraform output."""
    global AGENT_ARN
    if AGENT_ARN:
        return AGENT_ARN

    # Try terraform output
    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    result = subprocess.run(
        ["terraform", "output", "-raw", "agent_runtime_arn"],
        cwd=tf_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        AGENT_ARN = result.stdout.strip()
        return AGENT_ARN

    # Fallback: check environment variable
    arn = os.environ.get("SCF_AGENT_ARN")
    if arn:
        AGENT_ARN = arn
        return AGENT_ARN

    print("ERROR: Could not determine agent ARN.")
    print("Set SCF_AGENT_ARN env var or run from the project directory.")
    sys.exit(1)


def invoke(prompt: str, session_id: str = "cli-session") -> str:
    """Invoke the agent and return the response text."""
    arn = get_agent_arn()
    payload = json.dumps({"prompt": prompt, "session_id": session_id})
    payload_b64 = base64.b64encode(payload.encode()).decode()

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            [
                "aws", "bedrock-agentcore", "invoke-agent-runtime",
                "--agent-runtime-arn", arn,
                "--payload", payload_b64,
                "--region", REGION,
                tmp_path,
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )

        if result.returncode != 0:
            error = result.stderr.strip()
            if "RuntimeClientError" in error:
                return "[Agent Error] The agent returned an error. Check CloudWatch logs."
            return f"[CLI Error] {error}"

        # Read response
        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                data = json.loads(content)
                return data.get("response", content)
            except json.JSONDecodeError:
                return content
        else:
            return "[No response body returned]"
    except subprocess.TimeoutExpired:
        return "[Timeout] Agent did not respond within 5 minutes."
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def interactive_mode():
    """Run in interactive chat mode."""
    print("SCF Compliance Agent - Interactive Mode")
    print("Type 'quit' or 'exit' to stop. Type 'clear' for new session.")
    print("=" * 60)

    session_id = "cli-interactive"
    while True:
        try:
            prompt = input("\n📋 You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break

        if not prompt:
            continue
        if prompt.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        if prompt.lower() == "clear":
            session_id = f"cli-{os.urandom(4).hex()}"
            print("[Session cleared]")
            continue

        print("\n🔍 Thinking...\n")
        response = invoke(prompt, session_id)
        print(f"🤖 Agent:\n{response}")


def main():
    if "--interactive" in sys.argv or "-i" in sys.argv:
        interactive_mode()
        return

    # Single prompt mode
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-"):
        prompt = " ".join(sys.argv[1:])
    elif not sys.stdin.isatty():
        prompt = sys.stdin.read().strip()
    else:
        print(__doc__)
        sys.exit(1)

    if not prompt:
        print("No prompt provided.")
        sys.exit(1)

    response = invoke(prompt)
    print(response)


if __name__ == "__main__":
    main()
