"""
Answer Approval Page

Review, edit, approve, or reject draft answers extracted from questionnaires.
Approved answers become available to the agent for reuse.
"""

import json
from datetime import datetime

import boto3
import streamlit as st

REGION = "us-east-1"
ANSWERS_TABLE = "scf-agent-approved-answers"


@st.cache_resource
def get_table():
    dynamodb = boto3.resource("dynamodb", region_name=REGION)
    return dynamodb.Table(ANSWERS_TABLE)


def load_answers(status_filter="ALL"):
    """Load answers from DynamoDB."""
    table = get_table()
    response = table.scan(Limit=200)
    items = response.get("Items", [])
    
    if status_filter != "ALL":
        items = [i for i in items if i.get("status", "APPROVED") == status_filter]
    
    return sorted(items, key=lambda x: x.get("extracted_date", x.get("approved_date", "")), reverse=True)


def update_answer(answer_id: str, updates: dict):
    """Update an answer in DynamoDB."""
    table = get_table()
    
    update_expr_parts = []
    expr_values = {}
    expr_names = {}
    
    for key, value in updates.items():
        safe_key = f"#{key}"
        val_key = f":{key}"
        update_expr_parts.append(f"{safe_key} = {val_key}")
        expr_values[val_key] = value
        expr_names[safe_key] = key
    
    table.update_item(
        Key={"answer_id": answer_id},
        UpdateExpression="SET " + ", ".join(update_expr_parts),
        ExpressionAttributeValues=expr_values,
        ExpressionAttributeNames=expr_names,
    )


def delete_answer(answer_id: str):
    """Delete a rejected answer."""
    table = get_table()
    table.delete_item(Key={"answer_id": answer_id})


# --- Page UI ---

st.set_page_config(page_title="Approve Answers", page_icon="✅", layout="wide")
st.title("✅ Answer Approval Queue")
st.caption("Review and approve extracted questionnaire answers before they become available to the agent.")

# Sidebar filters
with st.sidebar:
    st.header("Filters")
    status_filter = st.selectbox("Status", ["DRAFT", "APPROVED", "REJECTED", "ALL"], index=0)
    
    st.header("Bulk Actions")
    approver_name = st.text_input("Your name (for approval)", value="")
    
    if st.button("🔄 Refresh"):
        st.cache_data.clear()
        st.rerun()

# Load answers
answers = load_answers(status_filter)

if not answers:
    st.info(f"No answers with status '{status_filter}'. Upload questionnaires to generate drafts.")
    st.stop()

st.write(f"**{len(answers)} answers** with status: {status_filter}")
st.divider()

# Display each answer with action buttons
for i, answer in enumerate(answers):
    with st.expander(
        f"{'📝' if answer.get('status') == 'DRAFT' else '✅' if answer.get('status') == 'APPROVED' else '❌'} "
        f"{answer.get('question_text', 'No question')[:80]}...",
        expanded=(status_filter == "DRAFT")
    ):
        col1, col2 = st.columns([3, 1])
        
        with col1:
            st.markdown(f"**Question:**")
            st.write(answer.get("question_text", ""))
            
            st.markdown(f"**Answer:**")
            edited_answer = st.text_area(
                "Edit answer text",
                value=answer.get("answer_text", ""),
                height=150,
                key=f"answer_{answer['answer_id']}",
                label_visibility="collapsed",
            )
        
        with col2:
            st.markdown(f"**Metadata:**")
            st.write(f"📁 Category: `{answer.get('category', 'N/A')}`")
            st.write(f"📋 Framework: `{answer.get('source_framework', 'N/A')}`")
            st.write(f"📄 Source: `{answer.get('source_document', 'N/A')}`")
            st.write(f"📅 Date: `{answer.get('extracted_date', answer.get('approved_date', 'N/A'))}`")
            st.write(f"🔖 Status: `{answer.get('status', 'N/A')}`")
            
            if answer.get("approved_by"):
                st.write(f"👤 Approved by: `{answer.get('approved_by')}`")
            if answer.get("extraction_method"):
                st.write(f"🔧 Extracted via: `{answer.get('extraction_method')}`")
        
        # Action buttons
        st.divider()
        btn_col1, btn_col2, btn_col3, btn_col4 = st.columns(4)
        
        with btn_col1:
            if st.button("✅ Approve", key=f"approve_{answer['answer_id']}", type="primary"):
                if not approver_name:
                    st.error("Enter your name in the sidebar first.")
                else:
                    updates = {
                        "status": "APPROVED",
                        "approved_by": approver_name,
                        "approved_date": datetime.utcnow().strftime("%Y-%m-%d"),
                        "answer_text": edited_answer,
                    }
                    update_answer(answer["answer_id"], updates)
                    st.success(f"Approved by {approver_name}")
                    st.rerun()
        
        with btn_col2:
            if st.button("💾 Save Edit", key=f"save_{answer['answer_id']}"):
                update_answer(answer["answer_id"], {"answer_text": edited_answer})
                st.success("Saved")
                st.rerun()
        
        with btn_col3:
            if st.button("❌ Reject", key=f"reject_{answer['answer_id']}"):
                update_answer(answer["answer_id"], {
                    "status": "REJECTED",
                    "approved_by": approver_name or "unknown",
                })
                st.warning("Rejected")
                st.rerun()
        
        with btn_col4:
            if st.button("🗑️ Delete", key=f"delete_{answer['answer_id']}"):
                delete_answer(answer["answer_id"])
                st.error("Deleted")
                st.rerun()

# Summary stats at bottom
st.divider()
all_answers = load_answers("ALL")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total", len(all_answers))
col2.metric("Approved", len([a for a in all_answers if a.get("status") == "APPROVED"]))
col3.metric("Draft", len([a for a in all_answers if a.get("status") == "DRAFT"]))
col4.metric("Rejected", len([a for a in all_answers if a.get("status") == "REJECTED"]))
