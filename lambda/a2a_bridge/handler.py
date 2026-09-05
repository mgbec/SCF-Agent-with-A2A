"""
A2A Bridge Lambda
=================

Terminates incoming Agent2Agent (A2A) protocol traffic in front of the Bedrock
AgentCore Runtime that hosts the SCF Compliance Agent.

Fronted by an API Gateway HTTP API (payload format 2.0) with two JWT authorizers:

    POST /cognito/rpc                        -> Amazon Cognito JWT authorizer
    GET  /cognito/.well-known/agent-card.json  (public)
    POST /entra/rpc                          -> Microsoft Entra ID JWT authorizer
    GET  /entra/.well-known/agent-card.json    (public)
    GET  /.well-known/agent-card.json          (public, generic card)

Token validation (signature, issuer, audience/expiry) is done by the API Gateway
JWT authorizer *before* this function runs, so this handler trusts
requestContext.authorizer.jwt.claims and only uses it for logging / session
namespacing.

ASYNC task model (API Gateway HTTP APIs cap the integration at ~30s):
    message/send  -> write a Task {state: "submitted"}, enqueue it on SQS, return
                     that Task immediately. A separate worker Lambda
                     (lambda/a2a_worker) runs the agent and updates the Task to
                     working -> completed / failed.
    tasks/get     -> read the Task from DynamoDB. Poll this until the state is
                     terminal (completed / failed / canceled). This is how a
                     client gets the answer.
    tasks/cancel  -> mark a non-terminal Task "canceled" (best effort).

NOT supported:
    message/stream / tasks/resubscribe   -> -32004 (capabilities.streaming = false;
        see docs/a2a-streaming.md for the options to add real incremental streaming)
    tasks/pushNotificationConfig/*       -> -32003
The message/send `configuration.blocking` flag is not honored - message/send is
always non-blocking (honoring it would re-introduce the 30s timeout).
"""

import base64
import hashlib
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TASKS_TABLE = os.environ["A2A_TASKS_TABLE"]
QUEUE_URL = os.environ["A2A_QUEUE_URL"]
TASK_TTL_SECONDS = int(os.environ.get("A2A_TASK_TTL_SECONDS", "86400"))

_sqs = boto3.client("sqs")
_tasks = boto3.resource("dynamodb").Table(TASKS_TABLE)

# AgentCore runtimeSessionId must match [A-Za-z0-9_-]{33,}
_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{33,}$")

JSONRPC = "2.0"
TERMINAL = {"completed", "failed", "canceled", "rejected"}

# JSON-RPC + A2A error codes
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
TASK_NOT_FOUND = -32001
TASK_NOT_CANCELABLE = -32002
PUSH_NOT_SUPPORTED = -32003
UNSUPPORTED_OPERATION = -32004

# CORS response headers are added by the API Gateway HTTP API (cors_configuration
# in terraform/a2a.tf), so the handler does not set them itself.


# --------------------------------------------------------------------------- #
# HTTP plumbing
# --------------------------------------------------------------------------- #
def _http(status, body, content_type="application/json", extra_headers=None):
    headers = {"Content-Type": content_type}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status,
        "headers": headers,
        "body": body if isinstance(body, str) else json.dumps(body),
        "isBase64Encoded": False,
    }


def _rpc_result(req_id, result):
    return _http(200, {"jsonrpc": JSONRPC, "id": req_id, "result": result})


def _rpc_error(req_id, code, message, data=None):
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return _http(200, {"jsonrpc": JSONRPC, "id": req_id, "error": err})


def _prefix_from_path(path: str):
    segs = [s for s in path.split("/") if s]
    if segs and segs[0] in ("cognito", "entra"):
        return segs[0]
    return None


def _caller_id(event) -> str:
    claims = (
        (event.get("requestContext", {}).get("authorizer", {}) or {})
        .get("jwt", {})
        .get("claims", {})
        or {}
    )
    return (
        claims.get("client_id")
        or claims.get("azp")
        or claims.get("appid")
        or claims.get("sub")
        or "anonymous"
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha_session(caller: str, context_id: str) -> str:
    """Per-(caller, context) AgentCore runtimeSessionId: 64 hex chars, so two
    callers that pass the same contextId don't share one AgentCore session."""
    return hashlib.sha256(f"{caller}:{context_id}".encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")
    prefix = _prefix_from_path(path)

    if method == "OPTIONS":
        return _http(204, "", content_type="text/plain")

    if method == "GET" and path.endswith("/.well-known/agent-card.json"):
        from agent_card import build_card

        return _http(200, build_card(prefix))

    if method == "POST" and path.endswith("/rpc"):
        return _handle_rpc(event, prefix)

    return _http(404, {"error": "not found", "path": path})


def _handle_rpc(event, prefix):
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")

    try:
        req = json.loads(raw)
    except (ValueError, TypeError):
        return _rpc_error(None, PARSE_ERROR, "Parse error")

    if not isinstance(req, dict) or req.get("jsonrpc") != JSONRPC or "method" not in req:
        req_id = req.get("id") if isinstance(req, dict) else None
        return _rpc_error(req_id, INVALID_REQUEST, "Invalid Request")

    req_id = req.get("id")
    rpc_method = req["method"]
    params = req.get("params") or {}
    caller = _caller_id(event)
    logger.info("A2A method=%s prefix=%s caller=%s", rpc_method, prefix, caller)

    try:
        if rpc_method == "message/send":
            return _rpc_result(req_id, _submit_message(params, caller))

        if rpc_method == "tasks/get":
            return _tasks_get(req_id, params)

        if rpc_method == "tasks/cancel":
            return _tasks_cancel(req_id, params)

        if rpc_method in ("message/stream", "tasks/resubscribe"):
            return _rpc_error(
                req_id,
                UNSUPPORTED_OPERATION,
                "Streaming is not supported (capabilities.streaming=false). "
                "Use message/send, then poll tasks/get.",
            )

        if rpc_method.startswith("tasks/pushNotificationConfig/"):
            return _rpc_error(req_id, PUSH_NOT_SUPPORTED, "Push notifications are not supported")

        return _rpc_error(req_id, METHOD_NOT_FOUND, f"Method not found: {rpc_method}")

    except ValueError as exc:  # raised for bad params
        return _rpc_error(req_id, INVALID_PARAMS, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("A2A request failed")
        return _rpc_error(req_id, INTERNAL_ERROR, f"Internal error: {exc}")


# --------------------------------------------------------------------------- #
# message/send -> submit + enqueue
# --------------------------------------------------------------------------- #
def _submit_message(params: dict, caller: str) -> dict:
    message = params.get("message") or {}
    text = _extract_text(message.get("parts") or [])
    if not text:
        raise ValueError("message.parts must contain at least one text or data part")

    incoming_context = message.get("contextId") or params.get("contextId")
    context_id = (
        incoming_context
        if isinstance(incoming_context, str) and _SESSION_RE.match(incoming_context)
        else uuid.uuid4().hex + uuid.uuid4().hex
    )
    runtime_session_id = _sha_session(caller, context_id)
    task_id = uuid.uuid4().hex + uuid.uuid4().hex

    input_message = dict(message)
    input_message["kind"] = "message"
    input_message["contextId"] = context_id
    input_message["taskId"] = task_id
    input_message.setdefault("messageId", uuid.uuid4().hex)

    task = {
        "kind": "task",
        "id": task_id,
        "contextId": context_id,
        "status": {"state": "submitted", "timestamp": _now_iso()},
        "artifacts": [],
        "history": [input_message],
    }
    _store_task(task, "submitted")

    _sqs.send_message(
        QueueUrl=QUEUE_URL,
        MessageBody=json.dumps(
            {
                "task_id": task_id,
                "prompt": text,
                "runtime_session_id": runtime_session_id,
                "context_id": context_id,
                "caller": caller,
            }
        ),
    )
    logger.info("A2A submitted task=%s context=%s", task_id, context_id)
    return task


def _extract_text(parts) -> str:
    chunks = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        kind = part.get("kind") or part.get("type")
        if kind == "text" and part.get("text"):
            chunks.append(str(part["text"]))
        elif kind == "data" and part.get("data") is not None:
            chunks.append(json.dumps(part["data"]))
    return "\n\n".join(chunks).strip()


# --------------------------------------------------------------------------- #
# Task store (DynamoDB, TTL)
# --------------------------------------------------------------------------- #
def _store_task(task: dict, state: str) -> None:
    _tasks.put_item(
        Item={
            "task_id": task["id"],
            "context_id": task.get("contextId", ""),
            "state": state,
            "task_json": json.dumps(task),
            "expires_at": int(time.time()) + TASK_TTL_SECONDS,
        }
    )


def _load_task(task_id):
    if not task_id:
        return None
    item = _tasks.get_item(Key={"task_id": task_id}).get("Item")
    if not item:
        return None
    return json.loads(item["task_json"])


def _tasks_get(req_id, params):
    task = _load_task(params.get("id"))
    if task is None:
        return _rpc_error(req_id, TASK_NOT_FOUND, "Task not found or expired")
    history_length = params.get("historyLength")
    if isinstance(history_length, int) and history_length >= 0:
        task["history"] = task.get("history", [])[-history_length:] if history_length else []
    return _rpc_result(req_id, task)


def _tasks_cancel(req_id, params):
    task = _load_task(params.get("id"))
    if task is None:
        return _rpc_error(req_id, TASK_NOT_FOUND, "Task not found or expired")
    if task["status"]["state"] in TERMINAL:
        return _rpc_error(
            req_id, TASK_NOT_CANCELABLE, f"Task is already {task['status']['state']}"
        )

    task["status"] = {"state": "canceled", "timestamp": _now_iso()}
    try:
        _tasks.update_item(
            Key={"task_id": params["id"]},
            UpdateExpression="SET #s = :s, task_json = :j",
            ConditionExpression="attribute_exists(#s) AND NOT (#s IN (:c, :f, :d, :r))",
            ExpressionAttributeNames={"#s": "state"},
            ExpressionAttributeValues={
                ":s": "canceled",
                ":j": json.dumps(task),
                ":c": "completed",
                ":f": "failed",
                ":d": "canceled",
                ":r": "rejected",
            },
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            # Worker finished between our read and write - return the final task.
            return _rpc_result(req_id, _load_task(params["id"]))
        raise
    return _rpc_result(req_id, task)
