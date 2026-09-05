# A2A streaming & long-run requests — options and trade-offs

The A2A bridge is **API Gateway HTTP API → submit Lambda → SQS → worker Lambda →
`InvokeAgentRuntime`**, with `tasks/get` backed by a 24-hour DynamoDB table.
`message/send` is non-blocking: it returns a `submitted` Task and the client polls
`tasks/get`. This doc records the analysis behind that design, and the options for
adding *real incremental streaming* on top of it, so a future change is a
decision, not a rediscovery.

**Option A (async task model) is implemented** — see §2. Options B and C (real
SSE) are not deployed; the async model stays as-is until someone picks one.

---

## 1. Current behavior, and why

The bridge (`lambda/a2a_bridge/handler.py`) is **submit-only**: `message/send`
writes a `Task {state: "submitted"}`, enqueues it on SQS, and returns that Task in
under a second. A separate worker Lambda (`lambda/a2a_worker/worker.py`, SQS-
triggered, 600 s timeout) runs the agent and advances the Task
`working → completed / failed` in the same DynamoDB table. The client polls
`tasks/get` until the state is terminal — that is how it gets the answer.
`tasks/cancel` marks a non-terminal Task `canceled` (best effort).

The Agent Card still advertises `capabilities.streaming = false`, and
`message/stream` / `tasks/resubscribe` return a JSON-RPC `-32004`: the async model
removes the timeout but does **not** deliver incremental frames.

Two hard AWS limits shaped this:

| Limit | Effect |
|---|---|
| **API Gateway HTTP API integration timeout is a fixed 30 s** (not configurable, applies to every integration type) | A synchronous `message/send` that ran the whole turn returned `503`/`504` to the caller once a turn passed ~30 s — even though the Lambda kept running and stored the task. The async model sidesteps this: the caller only ever waits on a sub-second submit and on short `tasks/get` polls. |
| **The Python *managed* Lambda runtime cannot stream a response body** | A Lambda-proxy response is fully buffered before the client sees byte one — so real "streaming" over the API Gateway path is impossible without Option B/C. |

What the async model gives you:

- No turn length limit for *getting an answer* — the worker has its own 600 s
  timeout, independent of the 30 s API Gateway cap.
- `tasks/get` retrieves the task from the store for 24 h — a caller that got cut
  off can still collect the result *if it has the task id* (it does: `message/send`
  returns it before any agent work starts).
- Auth is **API Gateway's native JWT authorizers** (Cognito + Entra ID), one per
  route, zero custom code — unchanged by the async model.
- SQS redelivery + DLQ (`maxReceiveCount` 2) for infra failures; the SQS event-
  source `maximum_concurrency` caps concurrent (expensive) Bedrock runs.
- Unsupported methods return clean JSON-RPC errors, and the card doesn't claim a
  capability the bridge doesn't have.

What it does **not** give you: incremental delivery. A slow query shows
`submitted` then `working` then the whole answer at once. See §2's progress
variant, or Options B/C, if that matters.

---

## 2. Option A — async task model (SQS + worker + poll) — **IMPLEMENTED**

Deployed in `terraform/a2a-async.tf` (+ edits to `terraform/a2a.tf`). Code:
`lambda/a2a_bridge/handler.py` (submit) and `lambda/a2a_worker/worker.py`
(worker).

```
POST /{prefix}/rpc  (message/send, non-blocking)
     │  JWT validated by the API Gateway authorizer (unchanged)
     ▼
 submit Lambda ──► DynamoDB  {task_id, state:"submitted"}   (returns in <1 s)
     │           └► SQS  {task_id, prompt, context_id}
     ▼
 202 / Task{state:"submitted"}  ──►  client

 SQS ──► worker Lambda  (timeout 600 s, event-source maximum_concurrency)
          • DynamoDB  state:"working"
          • InvokeAgentRuntime
          • DynamoDB  state:"completed" | "failed" + artifact
                      (conditional on state <> "canceled")
          • on error: SQS retry → DLQ after maxReceiveCount 2

 client polls  POST /{prefix}/rpc  {method:"tasks/get", params:{id}}
   submitted / working → keep polling
   completed / failed / canceled → done
```

- **Fixes the timeout completely.** No connection is held for more than a poll.
- **Keeps API Gateway's native Cognito/Entra authorizers** — no auth code.
- **Durability & backpressure for free:** SQS redelivery + DLQ; the event-source
  mapping's `scaling_config.maximum_concurrency` (`a2a_worker_max_concurrency`,
  default 5, min 2) caps concurrent (expensive) Bedrock runs *without* reserving
  account concurrency — the account's unreserved pool is small, so
  `reserved_concurrent_executions` on the worker is not used.
- **It is the A2A `Task` lifecycle** (`submitted → working → completed`, client
  polls `tasks/get`). `capabilities.streaming` is `false` — this option just makes
  `message/send` non-blocking instead of the client waiting on it.
- **`tasks/cancel` works:** a non-terminal Task is conditionally set `canceled`;
  the worker's final write is conditional on `state <> "canceled"`, so a worker
  that finishes just after a cancel logs a swallowed `ConditionalCheckFailedException`
  and does not clobber the `canceled` state.
- **Caller isolation:** the AgentCore `runtimeSessionId` is
  `sha256(f"{caller}:{context_id}")` (64 hex), so two callers passing the same
  `contextId` no longer share one AgentCore session. The `contextId` returned to
  the client is unchanged.
- Cost: polling latency (≤ the poll interval at the tail); a handful of extra
  API GW + Lambda + DynamoDB reads per request.
- Resources added: SQS work queue + DLQ, worker Lambda + role/policy + log group,
  event-source mapping. `message/send` reuses the existing bridge Lambda. No LWA /
  Function URL / in-app JWT code.

**Progress variant.** Have the worker write incremental `status.message` text
(or stage markers, if the agent ever exposes stages) into the task record between
Bedrock calls. `tasks/get` then shows live progress. This gets the "user stays
informed, nothing times out" benefit of streaming without holding a connection —
often all that's actually wanted.

---

## 3. Option B — Lambda Function URL + Lambda Web Adapter (real SSE, serverless)

A **separate** streaming endpoint for `message/stream` / `tasks/resubscribe`.

- Container-image Lambda; **Lambda Web Adapter** as a layer/extension
  (`AWS_LWA_INVOKE_MODE=response_stream`, `PORT=8000`); a **Function URL** with
  `InvokeMode=RESPONSE_STREAM`. A small Starlette/ASGI app runs under `uvicorn`.
- Duration is bounded only by the **Lambda timeout (≤ 15 min)** — not 30 s.
- Emits real incremental frames: `working` immediately, `: keep-alive\n\n`
  comments every ~10 s while the agent runs, then `artifact-update` +
  `completed`. Writes the finished `Task` to the same DynamoDB table so
  `tasks/get` on the API Gateway bridge still resolves it.

Sketch:

```python
# POST /{cognito|entra}/rpc  on the Function URL
claims = verify_jwt(bearer, issuer_for(prefix), audiences_for(prefix))  # PyJWT + JWKS cache
# ... parse JSON-RPC; only message/stream + tasks/resubscribe here ...

async def gen():
    yield sse({"kind": "status-update", "status": {"state": "working"}, "final": False})
    fut = asyncio.create_task(asyncio.to_thread(invoke_runtime, text, session_id))
    while not fut.done():
        done, _ = await asyncio.wait({fut}, timeout=10)
        if not done:
            yield ": keep-alive\n\n"
    try:
        answer = fut.result()
    except Exception as exc:
        yield sse({"kind": "status-update", "status": {"state": "failed"}, "final": True})
        yield sse({"error": {"code": -32603, "message": str(exc)}})
        return
    task = build_task(answer, ...)
    put_task(task)                       # same shape as the bridge's _run_message()
    yield sse({"kind": "artifact-update", "artifact": task["artifacts"][0], "lastChunk": True})
    yield sse({"kind": "status-update", "status": task["status"], "final": True})

return StreamingResponse(gen(), media_type="text/event-stream")
```

- **Pros:** genuine incremental delivery; \$0 at idle; stays serverless.
- **Cons:**
  - Function URLs can't attach an API Gateway authorizer, so the **bearer JWT is
    verified in code** — fetch each issuer's JWKS (`{cognito-issuer}/.well-known/jwks.json`,
    `https://login.microsoftonline.com/<tenant>/discovery/v2.0/keys`), cache per
    `kid`, verify RS256 + `exp` + `aud`/`client_id`. This must exactly mirror what
    API Gateway does for the two issuers — it's a real security surface.
  - Container image + LWA layer to maintain (LWA layer version pinning).
  - The Agent Card gains an `additionalInterfaces` entry pointing at the stream
    URL, and `message/stream` on the API Gateway `/rpc` route should then return a
    JSON-RPC error whose `data` points the client at the stream URL — a mild
    stretch of "one endpoint, method selects JSON vs SSE". Document it as
    deliberate.

---

## 4. Option C — ECS Fargate + ALB (real SSE, reuses frontend infra)

Run the same small ASGI streaming app as a Fargate service behind the **existing
frontend ALB** (its `idle_timeout` is already 3600 s) on a dedicated path.

- **Pros:** longest-lived connections; reuses ALB + CloudFront + VPC that already
  exist for the frontend.
- **Cons:** ~\$9/mo always-on; still needs **in-app JWT** — ALB
  `authenticate-oidc` runs a browser redirect/cookie flow and is not usable by
  machine-to-machine bearer callers.
- Pick this only if there is already a reason to run Fargate for A2A, or if the
  15-minute Function URL ceiling is genuinely too short.

---

## 5. Why not an API Gateway WebSocket API

It has no 30 s cap and is duplex — tempting. But A2A's wire contract is
**JSON-RPC over HTTP + SSE for `message/stream`**. Standard A2A clients
(`a2a-sdk`, `httpx-sse`) speak that, not a bespoke WebSocket transport. Switching
the bridge to WebSockets would break interoperability with off-the-shelf A2A
clients — the whole point of adopting the protocol.

---

## 6. Token-level streaming (a layer on top of B or C)

None of A/B/C stream **model tokens** — they stream *task lifecycle events*.
Getting per-token deltas to the caller additionally requires the **agent
container itself to stream**:

- Rewrite `agent/main.py` `/invocations` to emit `Content-Type: text/event-stream`
  from `agent.stream_async(prompt)` (Strands async streaming), writing
  `data: {...}\n\n` chunks as they arrive — the current blocking
  `http.server.HTTPServer` + `agent(prompt)` returns one blob and can't do this.
- The streaming bridge (B or C) then reads AgentCore's SSE response body
  line-by-line and forwards text deltas as `artifact-update` frames with
  `append: true`, ending with `lastChunk: true` + `completed`.
- Operational cost: an **ARM64 image rebuild** (`binfmt` is already registered on
  the build host — see `troubleshooting.md`), an `agent/update-runtime.ps1` roll,
  and a **retest of guardrail behavior under streaming**
  (`guardrail_stream_processing_mode`; a blocked guardrail mid-stream must produce
  a clean SSE error frame, not a truncated artifact).

---

## 7. Recommendation

| If "streaming" means… | Do |
|---|---|
| "stop timing out on long queries" | **Option A** — done |
| "let the caller watch progress" | **Option A + the progress variant** (2) — not done |
| "true incremental SSE frames" | **Option B** (or C) — not done |
| "true model-token stream" | **Option B/C + 6** — not done |

Effort / risk, low → high: **A < B < C < (B or C) + tokens**.

Two smaller issues that Option A already fixed in passing:

- **Caller isolation** — done. The AgentCore `runtimeSessionId` is now
  `_sha_session(caller, context_id)` = `sha256(f"{caller}:{context_id}")` in both
  `handler.py` and `worker.py`, so two callers passing the same `contextId` no
  longer share one AgentCore session.
- **`tasks/get` after a drop** — done. `message/send` returns the `task_id` before
  any agent work starts, so a client that is cut off mid-poll can still resume.

---

## 8. Comparison matrix

| | ~~Sync (was)~~ | **A — async + poll (now)** | B — Function URL + LWA | C — Fargate + ALB |
|---|---|---|---|---|
| 30 s timeout removed | ❌ | ✅ (worker 600 s) | ✅ (≤ 15 min) | ✅ (≤ ALB idle) |
| Incremental delivery to caller | ❌ buffered | ❌ poll | ✅ SSE | ✅ SSE |
| Model-token deltas | ❌ | ❌ | only with §6 | only with §6 |
| Auth | API GW JWT authorizer | API GW JWT authorizer | **in-app JWT** | **in-app JWT** |
| Packaging | zip Lambda | zip Lambdas | container + LWA | container + task defs |
| Durability / retries | none | **SQS + DLQ** | none | none |
| Backpressure / concurrency cap | none | **event-source `maximum_concurrency`** | none | task count |
| A2A spec fit | method → JSON/SSE on one URL | `Task` lifecycle (blessed) | per-method endpoint split | per-method endpoint split |
| Idle cost | \$0 | \$0 | \$0 | ~\$9/mo |
| New resources | — | worker Lambda + SQS + DLQ | 1 Lambda + ECR + Function URL | ECS svc + TG + listener rule |
