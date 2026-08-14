"""
SCF Compliance Agent - Local Web Frontend

A simple Streamlit chat interface for the SCF Compliance Agent.
Supports conversational interaction with session memory and report export.

Usage:
    pip install streamlit boto3
    streamlit run app.py
"""

import base64
import json
import os
import subprocess
import tempfile
from datetime import datetime

import boto3
import streamlit as st

# Configuration
REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ARN = os.environ.get("SCF_AGENT_ARN", "")


@st.cache_data
def get_agent_arn():
    """Get agent ARN from terraform output or environment."""
    if AGENT_ARN:
        return AGENT_ARN

    tf_dir = os.path.join(os.path.dirname(__file__), "..", "terraform")
    try:
        result = subprocess.run(
            ["terraform", "output", "-raw", "agent_runtime_arn"],
            cwd=tf_dir, capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass

    return ""


def invoke_agent(prompt: str, session_id: str) -> str:
    """Call the AgentCore runtime and return the response."""
    arn = get_agent_arn()
    if not arn:
        return "⚠️ Agent ARN not configured. Set SCF_AGENT_ARN environment variable or run from the project directory."

    payload_b64 = base64.b64encode(
        json.dumps({"prompt": prompt, "session_id": session_id}).encode()
    ).decode()

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
            capture_output=True, text=True, timeout=300,
        )

        if result.returncode != 0:
            error = result.stderr.strip()
            if "RuntimeClientError" in error:
                return "⚠️ The agent returned an error. The query may be too complex — try breaking it into smaller questions."
            return f"⚠️ Error: {error[:300]}"

        if os.path.exists(tmp_path) and os.path.getsize(tmp_path) > 0:
            with open(tmp_path, "r", encoding="utf-8") as f:
                content = f.read()
            try:
                data = json.loads(content)
                return data.get("response", content)
            except json.JSONDecodeError:
                return content

        return "Agent completed but returned no response body."
    except subprocess.TimeoutExpired:
        return "⚠️ Request timed out (5 min). Try a simpler question."
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


# --- Streamlit UI ---

st.set_page_config(
    page_title="SCF Compliance Agent",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ SCF Compliance Agent")
st.caption("Secure Controls Framework 2026.2 • 1,534 controls • 252+ frameworks")

# Sidebar
with st.sidebar:
    st.header("About")
    st.markdown("""
    This agent helps with:
    - **Gap analysis** against any framework
    - **Maturity assessment** (SCR-CMM Levels 0-5)
    - **Framework mapping** (HIPAA, NIST, ISO, PCI, NIS2...)
    - **Evidence checklists** for audits
    - **Compensating controls** for gaps
    - **Live web research** for current regulatory info
    """)

    st.divider()

    st.header("Quick Prompts")
    quick_prompts = [
        "What are the top HIPAA gaps if we have GOV-01, IAC-01, NET-01, CRY-01?",
        "Show me SCF control IAC-15 details",
        "What does Level 3 maturity look like for incident response?",
        "What controls map to EU NIS2?",
        "What evidence does a SOC 2 auditor need for access management?",
    ]
    for qp in quick_prompts:
        if st.button(qp[:50] + "...", key=qp):
            st.session_state.pending_prompt = qp

    st.divider()

    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.session_state.session_id = f"web-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        st.rerun()

    if st.button("💾 Export Chat as Report"):
        if st.session_state.get("messages"):
            report = "# SCF Compliance Agent - Chat Export\n\n"
            report += f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n---\n\n"
            for msg in st.session_state.messages:
                role = "**You:**" if msg["role"] == "user" else "**Agent:**"
                report += f"{role}\n\n{msg['content']}\n\n---\n\n"
            st.download_button(
                "📥 Download Report",
                report,
                file_name=f"scf-report-{datetime.now().strftime('%Y%m%d-%H%M%S')}.md",
                mime="text/markdown",
            )

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = f"web-{datetime.now().strftime('%Y%m%d%H%M%S')}"

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Handle quick prompt buttons
if "pending_prompt" in st.session_state:
    prompt = st.session_state.pending_prompt
    del st.session_state.pending_prompt

    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            response = invoke_agent(prompt, st.session_state.session_id)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
    st.rerun()

# Chat input
if prompt := st.chat_input("Ask about SCF controls, compliance gaps, maturity..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Analyzing..."):
            response = invoke_agent(prompt, st.session_state.session_id)
        st.markdown(response)

    st.session_state.messages.append({"role": "assistant", "content": response})
