"""
Generate a full compliance assessment report automatically.

Orchestrates multiple agent calls and assembles the results into a single
markdown report file. Handles the multi-step nature of complex queries
so the user doesn't have to.

Usage:
    python generate_report.py --framework HIPAA --controls GOV-01,IAC-01,IAC-15,NET-01,CRY-01
    python generate_report.py --framework "EU NIS2" --controls-file my_controls.txt
    python generate_report.py --framework "PCI DSS" --controls GOV-01,IAC-01 --output report.md
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime


REGION = "us-east-1"
AGENT_ARN = None


def get_agent_arn():
    global AGENT_ARN
    if AGENT_ARN:
        return AGENT_ARN
    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    result = subprocess.run(
        ["terraform", "output", "-raw", "agent_runtime_arn"],
        cwd=tf_dir, capture_output=True, text=True,
    )
    if result.returncode == 0:
        AGENT_ARN = result.stdout.strip()
        return AGENT_ARN
    AGENT_ARN = os.environ.get("SCF_AGENT_ARN", "")
    return AGENT_ARN


def invoke(prompt: str, session_id: str = "report-gen") -> str:
    """Invoke the agent and return response text."""
    arn = get_agent_arn()
    payload_b64 = base64.b64encode(
        json.dumps({"prompt": prompt, "session_id": session_id}).encode()
    ).decode()

    with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        result = subprocess.run(
            ["aws", "bedrock-agentcore", "invoke-agent-runtime",
             "--agent-runtime-arn", arn,
             "--payload", payload_b64,
             "--region", REGION, tmp_path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode != 0:
            return f"[Error: {result.stderr.strip()[:200]}]"

        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                data = json.loads(content)
                return data.get("response", content)
            except json.JSONDecodeError:
                return content
        return "[No response]"
    except subprocess.TimeoutExpired:
        return "[Timeout - agent took too long]"
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def generate_report(framework: str, controls: list, org_size: str = "medium", output_file: str = None):
    """Generate a full compliance report in multiple steps."""
    session_id = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    controls_str = ", ".join(controls)

    print(f"🔍 Generating {framework} compliance report...")
    print(f"   Controls: {len(controls)} implemented")
    print(f"   Org size: {org_size}")
    print()

    sections = []

    # Step 1: Gap Analysis
    print("  [1/4] Running gap analysis...")
    gap_response = invoke(
        f"Perform a {framework} gap analysis for a {org_size} organization. "
        f"Implemented controls: {controls_str}. "
        f"Show the top 10 missing controls prioritized by weight, with their "
        f"SCF ID, name, HIPAA/framework reference, and weight.",
        session_id
    )
    sections.append(("Gap Analysis", gap_response))

    # Step 2: Compensating Controls (first 5)
    print("  [2/4] Generating compensating controls (gaps 1-5)...")
    comp1_response = invoke(
        f"For the first 5 gaps you identified, provide compensating controls "
        f"that a {org_size} organization can implement within 90 days. Include "
        f"specific tools or processes for each.",
        session_id
    )
    sections.append(("Compensating Controls (Priority 1-5)", comp1_response))

    # Step 3: Compensating Controls (gaps 6-10)
    print("  [3/4] Generating compensating controls (gaps 6-10)...")
    comp2_response = invoke(
        f"Now provide compensating controls for gaps 6-10. Same format - "
        f"actionable steps for a {org_size} organization within 90 days.",
        session_id
    )
    sections.append(("Compensating Controls (Priority 6-10)", comp2_response))

    # Step 4: Evidence Checklist
    print("  [4/4] Building evidence request checklist...")
    evidence_response = invoke(
        f"For all 10 gaps, generate an evidence request checklist. For each control include: "
        f"SCF ID, control name, evidence artifacts needed (documents, configs, screenshots), "
        f"the ERL reference, conformity cadence, and responsible role.",
        session_id
    )
    sections.append(("Evidence Request Checklist", evidence_response))

    # Assemble report
    report = []
    report.append(f"# {framework} Compliance Assessment Report")
    report.append(f"")
    report.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"**Framework:** {framework}")
    report.append(f"**Organization Size:** {org_size}")
    report.append(f"**Controls Assessed:** {len(controls)}")
    report.append(f"**Implemented Controls:** {controls_str}")
    report.append(f"")
    report.append(f"---")
    report.append(f"")

    for title, content in sections:
        report.append(f"## {title}")
        report.append(f"")
        report.append(content)
        report.append(f"")
        report.append(f"---")
        report.append(f"")

    report_text = "\n".join(report)

    # Write output
    if not output_file:
        output_file = f"{framework.lower().replace(' ', '-')}-assessment-{datetime.now().strftime('%Y%m%d')}.md"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n✅ Report generated: {output_file}")
    print(f"   Size: {len(report_text):,} characters")
    return output_file


def main():
    parser = argparse.ArgumentParser(
        description="Generate SCF compliance assessment report",
        epilog="""
Examples:
  python generate_report.py --framework HIPAA --controls "GOV-01,IAC-01,NET-01,CRY-01"
  python generate_report.py --framework "EU NIS2" --controls-file controls.txt --org-size medium
  python generate_report.py --prompt "We're a 175-person healthcare company preparing for HIPAA..."
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--framework", help="Target framework (HIPAA, 'EU NIS2', 'PCI DSS', etc.)")
    parser.add_argument("--controls", default="", help="Comma-separated implemented SCF control IDs")
    parser.add_argument("--controls-file", help="File with one control ID per line")
    parser.add_argument("--org-size", default="medium",
                        choices=["micro_small", "small", "medium", "large", "enterprise"])
    parser.add_argument("--output", help="Output file path")
    parser.add_argument("--prompt", help="Natural language description (auto-generates report)")

    args = parser.parse_args()

    if args.prompt:
        # Natural language mode - run the full prompt in steps
        generate_from_prompt(args.prompt, args.output)
        return

    if not args.framework:
        parser.print_help()
        sys.exit(1)

    controls = []
    if args.controls:
        controls = [c.strip() for c in args.controls.split(",") if c.strip()]
    elif args.controls_file:
        with open(args.controls_file, "r") as f:
            controls = [line.strip() for line in f if line.strip() and not line.startswith("#")]

    if not controls:
        print("ERROR: Provide controls via --controls, --controls-file, or use --prompt")
        sys.exit(1)

    generate_report(args.framework, controls, args.org_size, args.output)


def generate_from_prompt(prompt: str, output_file: str = None):
    """Generate report from a natural language prompt by breaking into steps."""
    session_id = f"report-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print("🔍 Generating compliance report from your prompt...")
    print(f"   Prompt: {prompt[:80]}...")
    print()

    sections = []

    # Step 1: Gap analysis
    print("  [1/3] Analyzing gaps...")
    gap_prompt = f"{prompt}\n\nFocus on: identify the top 10 compliance gaps, prioritized by weight. For each gap show the SCF control ID, name, framework reference, and weight."
    gap_response = invoke(gap_prompt, session_id)
    sections.append(("Compliance Gap Analysis", gap_response))

    # Step 2: Compensating controls
    print("  [2/3] Generating compensating controls and remediation...")
    comp_prompt = "For the gaps you just identified, provide compensating controls for each. Include specific actionable steps, tools or processes to implement, and a realistic timeline."
    comp_response = invoke(comp_prompt, session_id)
    sections.append(("Compensating Controls & Remediation", comp_response))

    # Step 3: Evidence checklist
    print("  [3/3] Building evidence request checklist...")
    evidence_prompt = "Now generate an evidence request checklist for each gap. Include: evidence artifacts needed (documents, screenshots, configs), the responsible role, and how often evidence must be refreshed."
    evidence_response = invoke(evidence_prompt, session_id)
    sections.append(("Evidence Request Checklist", evidence_response))

    # Assemble
    report = []
    report.append("# Compliance Assessment Report")
    report.append(f"\n**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"\n**Request:** {prompt}")
    report.append("\n---\n")

    for title, content in sections:
        report.append(f"## {title}\n")
        report.append(content)
        report.append("\n---\n")

    report_text = "\n".join(report)

    if not output_file:
        output_file = f"compliance-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md"

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n✅ Report generated: {output_file}")
    print(f"   Size: {len(report_text):,} characters")


if __name__ == "__main__":
    main()
