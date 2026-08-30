"""
SCF Compliance Agent - Local Web Frontend

A simple Streamlit chat interface for the SCF Compliance Agent.
Supports conversational interaction with session memory and report export.

Usage:
    pip install streamlit boto3
    streamlit run app.py
"""

import json
import os
import subprocess
import uuid
from datetime import datetime

import boto3
import streamlit as st

from auth import render_logout_sidebar, require_login

# Configuration
REGION = os.environ.get("AWS_REGION", "us-east-1")
AGENT_ARN = os.environ.get("SCF_AGENT_ARN", "")

_agentcore = boto3.client("bedrock-agentcore", region_name=REGION)


def _new_session_id() -> str:
    """A runtimeSessionId AgentCore accepts (>=33 chars of [A-Za-z0-9_-])."""
    return f"web-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex}"


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
    """Call the AgentCore runtime via boto3 and return the response text."""
    arn = get_agent_arn()
    if not arn:
        return "⚠️ Agent ARN not configured. Set the SCF_AGENT_ARN environment variable or run from the project directory."

    if len(session_id) < 33:
        session_id = _new_session_id()

    try:
        resp = _agentcore.invoke_agent_runtime(
            agentRuntimeArn=arn,
            runtimeSessionId=session_id,
            qualifier="DEFAULT",
            contentType="application/json",
            accept="application/json",
            payload=json.dumps({"prompt": prompt, "session_id": session_id}).encode("utf-8"),
        )
    except Exception as e:  # noqa: BLE001 - surface any boto/runtime error to the user
        msg = str(e)
        if "RuntimeClientError" in msg or "424" in msg:
            return "⚠️ The agent returned an error. The query may be too complex — try breaking it into smaller questions."
        return f"⚠️ Error invoking agent: {msg[:300]}"

    body = resp.get("response")
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")
    if not body:
        return "Agent completed but returned no response body."

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body
    if isinstance(data, dict):
        return data.get("response") or data.get("output") or data.get("message") or body
    return str(data)


# --- Streamlit UI ---

st.set_page_config(
    page_title="SCF Compliance Agent",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Require authentication before rendering any content
require_login()
render_logout_sidebar()

# Override the default page name in sidebar navigation
st.html("<style>[data-testid='stSidebarNav'] li:first-child a span {visibility:hidden; position:relative;} [data-testid='stSidebarNav'] li:first-child a span::after {content:'💬 Chat'; visibility:visible; position:absolute; left:0;}</style>")

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
        st.session_state.session_id = _new_session_id()
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
    st.session_state.session_id = _new_session_id()

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
