"""
A2A Worker Lambda
=================

SQS-triggered. Runs one A2A task to completion, out of band from the API Gateway
request that submitted it, so a long agent turn no longer hits API Gateway's
~30-second integration timeout.

Flow (one message per invocation, batch_size = 1):

    submit (a2a_bridge)  -->  DynamoDB {state: "submitted"}  -->  SQS
    this worker           -->  DynamoDB {state: "working"}
                          -->  bedrock-agentcore:InvokeAgentRuntime
                          -->  DynamoDB {state: "completed", artifact}   (unless canceled)
    handled agent error   -->  DynamoDB {state: "failed", message}, message consumed
    infra error / crash   -->  SQS redrive -> DLQ after maxReceiveCount

The client polls `tasks/get` on the bridge until the state is terminal.
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
TASKS_TABLE = os.environ["A2A_TASKS_TABLE"]

_agentcore = boto3.client("bedrock-agentcore")
_tasks = boto3.resource("dynamodb").Table(TASKS_TABLE)

TERMINAL = {"completed", "failed", "canceled", "rejected"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    for record in event.get("Records", []):
        try:
            _process(json.loads(record["body"]))
        except Exception:  # noqa: BLE001 - let it propagate so SQS retries -> DLQ
            logger.exception("A2A worker: unhandled error, message will be retried")
            raise
    return {"batchItemFailures": []}


def _process(msg: dict) -> None:
    task_id = msg["task_id"]
    prompt = msg["prompt"]
    session_id = msg["runtime_session_id"]
    caller = msg.get("caller", "unknown")
    context_id = msg.get("context_id", "")

    logger.info("A2A worker task=%s caller=%s session=%s", task_id, caller, session_id[:12])

    current = _load_task(task_id)
    if current is None:
        logger.warning("task %s not found (expired?), dropping", task_id)
        return
    if current["status"]["state"] in TERMINAL:
        logger.info("task %s already %s, dropping", task_id, current["status"]["state"])
        return

    _set_state(task_id, current, "working")

    try:
        answer = _invoke_runtime(prompt, session_id)
    except Exception as exc:  # noqa: BLE001 - agent/runtime failure -> mark failed, consume
        logger.exception("InvokeAgentRuntime failed for task %s", task_id)
        _fail(task_id, current, context_id, f"Agent runtime error: {exc}")
        return

    _finish(task_id, current, context_id, answer)


# --------------------------------------------------------------------------- #
# AgentCore
# --------------------------------------------------------------------------- #
def _invoke_runtime(prompt: str, session_id: str) -> str:
    payload = json.dumps({"prompt": prompt, "session_id": session_id}).encode("utf-8")
    resp = _agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        runtimeSessionId=session_id,
        qualifier=AGENT_RUNTIME_QUALIFIER,
        contentType="application/json",
        accept="application/json",
        payload=payload,
    )
    body = resp.get("response")
    if hasattr(body, "read"):
        body = body.read()
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", errors="replace")

    try:
        data = json.loads(body)
    except (ValueError, TypeError):
        return body if isinstance(body, str) else str(body)

    if isinstance(data, dict):
        return (
            data.get("response")
            or data.get("output")
            or data.get("message")
            or data.get("completion")
            or json.dumps(data)
        )
    return str(data)


# --------------------------------------------------------------------------- #
# Task store
# --------------------------------------------------------------------------- #
def _load_task(task_id):
    item = _tasks.get_item(Key={"task_id": task_id}).get("Item")
    return json.loads(item["task_json"]) if item else None


def _set_state(task_id: str, task: dict, state: str) -> None:
    """Best-effort state bump (e.g. -> working). Not conditional."""
    task["status"] = {"state": state, "timestamp": _now_iso()}
    _tasks.update_item(
        Key={"task_id": task_id},
        UpdateExpression="SET #s = :s, task_json = :j",
        ExpressionAttributeNames={"#s": "state"},
        ExpressionAttributeValues={":s": state, ":j": json.dumps(task)},
    )


def _finish(task_id: str, task: dict, context_id: str, answer: str) -> None:
    now = _now_iso()
    agent_message = {
        "kind": "message",
        "role": "agent",
        "messageId": uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": answer}],
        "contextId": context_id,
        "taskId": task_id,
    }
    task["status"] = {"state": "completed", "timestamp": now, "message": agent_message}
    task["artifacts"] = [
        {"artifactId": uuid.uuid4().hex, "name": "response", "parts": [{"kind": "text", "text": answer}]}
    ]
    task.setdefault("history", []).append(agent_message)
    _conditional_write(task_id, task, "completed")


def _fail(task_id: str, task: dict, context_id: str, error_text: str) -> None:
    now = _now_iso()
    err_message = {
        "kind": "message",
        "role": "agent",
        "messageId": uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": error_text}],
        "contextId": context_id,
        "taskId": task_id,
    }
    task["status"] = {"state": "failed", "timestamp": now, "message": err_message}
    task.setdefault("history", []).append(err_message)
    _conditional_write(task_id, task, "failed")


def _conditional_write(task_id: str, task: dict, state: str) -> None:
    """Write the terminal state unless the client canceled the task meanwhile."""
    try:
        _tasks.update_item(
            Key={"task_id": task_id},
            UpdateExpression="SET #s = :s, task_json = :j",
            ConditionExpression="attribute_not_exists(#s) OR #s <> :canceled",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={":s": state, ":j": json.dumps(task), ":canceled": "canceled"},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            logger.info("task %s was canceled; not overwriting with %s", task_id, state)
            return
        raise
