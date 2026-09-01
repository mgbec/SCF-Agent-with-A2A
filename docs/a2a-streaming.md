# A2A streaming & long-run requests — options and trade-offs

The A2A bridge today is deliberately simple: **API Gateway HTTP API → one Lambda →
`InvokeAgentRuntime`**, with `tasks/get` backed by a 24-hour DynamoDB table. That
shape has one limitation worth understanding, and several ways to lift it. This
doc records the analysis so a future change is a decision, not a rediscovery.

**Nothing here is deployed.** The current setup stays as-is until someone
deliberately picks an option below.

---

## 1. Current behaviour, and why

`message/stream` returns a **valid `text/event-stream` body, but buffered**: the
bridge (`lambda/a2a_bridge/handler.py`) runs the agent to completion, then
`_sse()` concatenates the three frames (`working` → `artifact-update` →
`completed`) into a single response. `message/send` returns the completed `Task`
as JSON the same way.

Two hard AWS limits cause this:

| Limit | Effect |
|---|---|
| **API Gateway HTTP API integration timeout is a fixed 30 s** (not configurable, applies to every integration type) | Any turn that takes longer than ~30 s returns `504` to the caller — even though the Lambda keeps running and stores the task |
| **The Python *managed* Lambda runtime cannot stream a response body** | Even without the 30 s cap, a Lambda-proxy response is fully buffered before the client sees byte one — so "streaming" over this path can only ever be fake |

What works well today and shouldn't be lost:

- Short/medium queries (most control lookups, framework mappings, targeted gap
  questions) finish inside 30 s.
- `tasks/get` / `tasks/resubscribe` retrieve a completed task from the store for
  24 h — a caller that gets cut off can still collect the result *if it has the
  task id* (see the caveat in §7).
- Auth is **API Gateway's native JWT authorizers** (Cognito + Entra ID), one per
  route, zero custom code.
- Unsupported methods return clean JSON-RPC errors.

---

## 2. Option A — async task model (SQS + worker + poll)

```
POST /{prefix}/rpc  (message/send, non-blocking)
     │  JWT validated by the API Gateway authorizer (unchanged)
     ▼
 submit Lambda ──► DynamoDB  {task_id, state:"submitted"}   (returns in <1 s)
     │           └► SQS  {task_id, prompt, context_id}
     ▼
 202 / Task{state:"submitted"}  ──►  client

 SQS ──► worker Lambda  (timeout up to 15 min, reserved concurrency)
          • DynamoDB  state:"working"
          • InvokeAgentRuntime
          • DynamoDB  state:"completed" | "failed" + artifact
          • on error: SQS retry → DLQ after N attempts

 client polls  POST /{prefix}/rpc  {method:"tasks/get", params:{id}}
   submitted / working → keep polling
   completed / failed  → done
```

- **Fixes the timeout completely.** No connection is held for more than a poll.
- **Keeps API Gateway's native Cognito/Entra authorizers** — no auth code.
- **Durability & backpressure for free:** SQS redelivery + DLQ; reserved
  concurrency on the worker caps concurrent (expensive) Bedrock runs.
- **It is the A2A `Task` lifecycle** (`submitted → working → completed`, client
  polls `tasks/get`). Set `capabilities.streaming` to an honest `false`.
- Cost: polling latency (≤ the poll interval at the tail); a handful of extra
  API GW + Lambda + DynamoDB reads per request.
- New resources: submit Lambda + worker Lambda + SQS queue + DLQ + event-source
  mapping + their IAM. Each piece is simple; there's no LWA / Function URL / JWT
  code.

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
  and a **retest of guardrail behaviour under streaming**
  (`guardrail_stream_processing_mode`; a blocked guardrail mid-stream must produce
  a clean SSE error frame, not a truncated artifact).

---

## 7. Recommendation

| If "streaming" means… | Do |
|---|---|
| "stop 504-ing on long queries" | **Option A** |
| "let the caller watch progress" | **Option A + the progress variant** (§2) |
| "true incremental SSE frames" | **Option B** (or C) |
| "true model-token stream" | **Option B/C + §6** |

Effort / risk, low → high: **A < B < C < (B or C) + tokens**.

Whatever is chosen, also fix the two smaller issues the same code touches:

- **Caller isolation.** `_run_message` maps the caller's `contextId` straight
  onto the AgentCore `runtimeSessionId`; two callers passing the same `contextId`
  share one session. Namespace it as `hash(caller_id + contextId)` —
  `_caller_id()` already computes the identity and currently only logs it.
- **`tasks/get` after a drop.** A client that gets cut off before receiving the
  response never learns the `task_id`, so it can't poll. Return the `task_id`
  early (Option A does this by design; for B, emit it in the first `working`
  frame — the bridge already generates it up front).

---

## 8. Comparison matrix

| | Current | A — async + poll | B — Function URL + LWA | C — Fargate + ALB |
|---|---|---|---|---|
| 30 s timeout removed | ❌ | ✅ | ✅ (≤ 15 min) | ✅ (≤ ALB idle) |
| Incremental delivery to caller | ❌ buffered | ❌ poll | ✅ SSE | ✅ SSE |
| Model-token deltas | ❌ | ❌ | only with §6 | only with §6 |
| Auth | API GW JWT authorizer | API GW JWT authorizer | **in-app JWT** | **in-app JWT** |
| Packaging | zip Lambda | zip Lambdas | container + LWA | container + task defs |
| Durability / retries | none | **SQS + DLQ** | none | none |
| Backpressure / concurrency cap | none | **worker reserved concurrency** | none | task count |
| A2A spec fit | method → JSON/SSE on one URL | `Task` lifecycle (blessed) | per-method endpoint split | per-method endpoint split |
| Idle cost | \$0 | \$0 | \$0 | ~\$9/mo |
| New resources | — | 2 Lambda + SQS + DLQ | 1 Lambda + ECR + Function URL | ECS svc + TG + listener rule |
