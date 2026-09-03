"""
A2A Bridge Lambda
=================

Terminates incoming Agent2Agent (A2A) protocol traffic and forwards it to the
existing Bedrock AgentCore Runtime that hosts the SCF Compliance Agent.

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

Supported JSON-RPC methods:
    message/send        -> invoke the runtime, return a completed Task (JSON)
    tasks/get           -> fetch a recently completed Task from DynamoDB (24h TTL)

NOT supported (the Agent Card advertises capabilities.streaming = false):
    message/stream / tasks/resubscribe -> return -32004; this bridge does not
        stream (API Gateway HTTP APIs buffer + cap at 30s, and the Python managed
        Lambda runtime can't stream). Use message/send, then poll tasks/get.
        See docs/a2a-streaming.md for the options to add real streaming.
Everything else returns a standard JSON-RPC error (see A2A error codes below).
"""

import base64
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

import boto3

logger = logging.getLogger()
logger.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

AGENT_RUNTIME_ARN = os.environ["AGENT_RUNTIME_ARN"]
AGENT_RUNTIME_QUALIFIER = os.environ.get("AGENT_RUNTIME_QUALIFIER", "DEFAULT")
TASKS_TABLE = os.environ["A2A_TASKS_TABLE"]
TASK_TTL_SECONDS = int(os.environ.get("A2A_TASK_TTL_SECONDS", "86400"))

_agentcore = boto3.client("bedrock-agentcore")
_tasks = boto3.resource("dynamodb").Table(TASKS_TABLE)

# AgentCore runtimeSessionId must match [A-Za-z0-9_-]{33,}
_SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]{33,}$")

JSONRPC = "2.0"

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
CONTENT_TYPE_NOT_SUPPORTED = -32005

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
            task = _run_message(params)
            return _rpc_result(req_id, task)

        if rpc_method == "tasks/get":
            return _tasks_get(req_id, params)

        if rpc_method in ("message/stream", "tasks/resubscribe"):
            return _rpc_error(
                req_id,
                UNSUPPORTED_OPERATION,
                "Streaming is not supported (capabilities.streaming=false). "
                "Use message/send, then poll tasks/get.",
            )

        if rpc_method == "tasks/cancel":
            return _rpc_error(
                req_id, TASK_NOT_CANCELABLE, "Task cannot be canceled (synchronous execution)"
            )

        if rpc_method.startswith("tasks/pushNotificationConfig/"):
            return _rpc_error(req_id, PUSH_NOT_SUPPORTED, "Push notifications are not supported")

        return _rpc_error(req_id, METHOD_NOT_FOUND, f"Method not found: {rpc_method}")

    except ValueError as exc:  # raised by _run_message for bad params
        return _rpc_error(req_id, INVALID_PARAMS, str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("A2A request failed")
        return _rpc_error(req_id, INTERNAL_ERROR, f"Internal error: {exc}")


# --------------------------------------------------------------------------- #
# A2A <-> AgentCore
# --------------------------------------------------------------------------- #
def _run_message(params: dict) -> dict:
    """Handle message/send: invoke the runtime, build + store a Task."""
    message = params.get("message") or {}
    text = _extract_text(message.get("parts") or [])
    if not text:
        raise ValueError("message.parts must contain at least one text or data part")

    incoming_context = message.get("contextId") or params.get("contextId")
    session_id = (
        incoming_context
        if isinstance(incoming_context, str) and _SESSION_RE.match(incoming_context)
        else uuid.uuid4().hex + uuid.uuid4().hex
    )
    context_id = session_id
    task_id = uuid.uuid4().hex + uuid.uuid4().hex

    answer = _invoke_runtime(text, session_id)
    now = _now_iso()

    input_message = dict(message)
    input_message["kind"] = "message"
    input_message["contextId"] = context_id
    input_message["taskId"] = task_id
    input_message.setdefault("messageId", uuid.uuid4().hex)

    agent_message = {
        "kind": "message",
        "role": "agent",
        "messageId": uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": answer}],
        "contextId": context_id,
        "taskId": task_id,
    }

    task = {
        "kind": "task",
        "id": task_id,
        "contextId": context_id,
        "status": {"state": "completed", "timestamp": now, "message": agent_message},
        "artifacts": [
            {
                "artifactId": uuid.uuid4().hex,
                "name": "response",
                "parts": [{"kind": "text", "text": answer}],
            }
        ],
        "history": [input_message, agent_message],
    }
    _store_task(task)
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
# Task store (DynamoDB, TTL)
# --------------------------------------------------------------------------- #
def _store_task(task: dict) -> None:
    _tasks.put_item(
        Item={
            "task_id": task["id"],
            "context_id": task.get("contextId", ""),
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
