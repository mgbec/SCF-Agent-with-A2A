# Deployment Decisions & Lessons Learned

This document captures key architectural decisions, tradeoffs, and issues
encountered while deploying the SCF Compliance Agent on Bedrock AgentCore.

## ECR Container vs S3 Code Deploy

AgentCore Runtime supports two deployment methods:

| Method | How It Works |
|--------|-------------|
| **Container (ECR)** | You build a Docker image, push to ECR, AgentCore pulls it at runtime |
| **Code Deploy (S3)** | You zip your Python code, upload to S3, AgentCore installs dependencies at cold start |

### We chose ECR. Here's why.

**The S3 code deploy method failed for this project** because AgentCore has a
**30-second initialization timeout**. When the runtime boots a code-deploy agent,
it runs `pip install -r requirements.txt` at startup. Our dependencies
(`strands-agents`, `boto3`, `pydantic`, and their transitive dependencies) take
60-90 seconds to install — well past the 30s limit.

We tried several mitigations:
1. **Lazy imports** — Move all heavy imports to first request, not module load.
   Didn't help because pip install happens before your code even runs.
2. **Removing packages** — Stripping `strands-agents-tools` helped slightly but
   `strands-agents` alone still pulls in pydantic, httpx, opentelemetry, etc.
3. **Pre-bundling vendor directory** — Include dependencies in the zip. This
   bloats the zip to 100MB+ and still requires Python to process the packages
   at boot under the managed runtime.

**Container deployment solves this completely** because dependencies are baked
into the image at build time. Cold start is just "start Python, run main.py" —
no pip install, no network downloads, no compilation.

### When S3 Code Deploy would work

- Agents with minimal dependencies (just boto3 + stdlib)
- Agents with only pure-Python packages that install instantly
- Prototyping where you want fast iteration without Docker builds

### ECR container tradeoffs

| Pro | Con |
|-----|-----|
| Deterministic startup (no pip at boot) | Requires Docker for builds |
| Full control over system deps | ARM64 cross-compilation is slow on x86 |
| Cached layers speed rebuilds | ECR costs (minimal, but non-zero) |
| Works with any Python version + native libs | Image must be ARM64 (Graviton) |

## ARM64 Requirement

AgentCore Runtime runs exclusively on **AWS Graviton (ARM64)** processors.
This means:

- Container images **must** be `linux/arm64` architecture
- If you build on an x86 machine (most dev laptops), you need cross-compilation
- `docker buildx build --platform linux/arm64` with QEMU emulation works but is
  **5-10x slower** than native builds

### The build performance problem

On an x86 Windows machine with Docker Desktop:

| Approach | Build Time | Notes |
|----------|-----------|-------|
| Native amd64 build | ~100s | Fast but wrong architecture |
| ARM64 with QEMU (compile from source) | 12-15 min | pydantic-core has Rust that kills perf |
| ARM64 with QEMU (only-binary wheels) | ~2.5 min | No compilation, just wheel unpacking |
| Native ARM64 machine (CI/CD) | ~60s | Best option for production |

### Recommendations for production

1. **Use AWS CodeBuild with ARM64 compute** — Build the image in CI/CD on a
   Graviton instance. No QEMU overhead. The awslabs AgentCore samples use this pattern.
2. **Use GitHub Actions with `runs-on: ubuntu-latest-arm64`** — Native ARM64 runners.
3. **Cache the pip layer** — Since `requirements.txt` rarely changes, the Docker
   layer cache means rebuilds after code changes take seconds, not minutes.

### Local development tip

Use `--only-binary=:all:` in the Dockerfile to avoid QEMU compiling native
extensions. This tells pip to only download pre-built wheels:

```dockerfile
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt
```

This reduced our cross-platform build from 12+ minutes to ~2.5 minutes.

## Knowledge Base: S3 Vectors vs OpenSearch Serverless

### We chose S3 Vectors. Here's the decision path.

| Backend | Complexity | Cost | Managed |
|---------|-----------|------|---------|
| OpenSearch Serverless | High (collection, indexes, access policies, encryption policies) | $$$ (OCU charges even when idle) | Partially |
| S3 Vectors | Low (bucket + index, 2 CLI commands) | $ (pay per query) | Fully |

We initially tried OpenSearch Serverless but hit:
1. Collection takes 60-90s to become ACTIVE
2. Vector index must be created via API (not Terraform) before KB can use it
3. Complex access policies with exact principal matching
4. The Terraform provider doesn't create the index — you need curl/awscurl with SigV4

**S3 Vectors** eliminated all of that. Two CLI commands (`create-vector-bucket`,
`create-index`) and you're done. No idle costs, no collection management.

### The "unable to assume role" saga

The Bedrock KB API returns a misleading error: `"Bedrock Knowledge Base was unable
to assume the given role"` — which actually means several different things:

| Actual Cause | What the error says |
|-------------|-------------------|
| IAM role not yet propagated | "unable to assume the given role" |
| Missing `s3vectors:QueryVectors` permission | "unable to assume the given role" |
| Empty `s3VectorsConfiguration` (no auto-create) | "unable to assume the given role" |
| Missing `bedrock:ListFoundationModels` permission | "unable to assume the given role" |

**Resolution:** You must:
1. Create the S3 Vectors bucket and index **before** the KB
2. Pass explicit `vector_bucket_arn` + `index_name` (not empty config)
3. Grant `s3vectors:*` on the specific bucket/index ARN
4. Grant `bedrock:ListFoundationModels` + `bedrock:InvokeModel`
5. Include `aws:SourceAccount` + `aws:SourceArn` conditions in the trust policy

## AgentCore Naming Constraints

Different AgentCore resources have **different** naming regex:

| Resource | Pattern | Allowed |
|----------|---------|---------|
| `agent_runtime`, `memory` | `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` | Underscores only, no hyphens |
| `gateway`, `gateway_target` | `^([0-9a-zA-Z][-]?){1,100}$` | Hyphens only, no underscores |

This means you can't use a single naming convention across all resources.
The Terraform uses `replace(local.name_prefix, "-", "_")` for runtime/memory
resources while keeping hyphens for gateway resources.

## Web Search Connector

The Bedrock AgentCore Web Search Tool is a managed MCP connector. As of
AWS provider 6.56, there's **no native Terraform resource** for connector-type
gateway targets. We provision it via a `terraform_data` + `local-exec` CLI call.

Known issues:
- JSON escaping in PowerShell requires writing to a temp file
- The connector target isn't tracked in Terraform state (manual cleanup on destroy)
- Provider may add native support in a future version

## Gateway Target Provider Bug

The `aws_bedrockagentcore_gateway_target` resource for HTTP targets produces a
"Provider produced inconsistent result" error on first apply:

```
.credential_provider_configuration: block count changed from 0 to 1
```

The API always returns a `credential_provider_configuration { gateway_iam_role {} }`
block for an `agentcore_runtime` target; the provider didn't expect it. Left
undeclared, every `terraform plan` also perpetually tried to remove it.

**Fix:** declare the block so the config matches the API. `terraform/main.tf` now
has it, and `terraform plan` is clean. (The old `-refresh-only` workaround only
silenced the state mismatch for one apply.)

## Frontend hosting: not App Runner

The Streamlit frontend was first put on **AWS App Runner** (simple, free HTTPS URL,
no VPC). It doesn't work: **App Runner has no WebSocket support**, and Streamlit's
entire UI runs over a `/_stcore/stream` WebSocket — the page loads the shell and
then hangs on the loading skeleton.

Chosen instead: **ECS Fargate behind an ALB, with CloudFront in front.** CloudFront
gives a free HTTPS `*.cloudfront.net` domain (no ACM cert / custom domain needed)
and forwards WebSockets; the ALB and Fargate handle the rest. CloudFront injects a
secret `X-Origin-Verify` header and the ALB 403s anything without it, so the ALB
can't be reached directly. ~$25-35/mo (ALB + always-on task). See
`docs/frontend-deployment.md`.

Lightsail container service also supports WebSockets and is cheaper, but Lightsail
containers can't assume an IAM role — you'd bake a static access key into the
image — so it was rejected on security grounds.

## ARM64 builds and QEMU binfmt

On an x86 build host, `docker build --platform linux/arm64` depends on QEMU
`binfmt_misc` handlers. If they aren't registered, cross-arch `RUN` steps fail with
`exec /bin/sh: exec format error`, and — depending on layer cache — the build can
**silently reuse the previous image** and `docker push` becomes a no-op. The agent
then keeps running old code even though the pipeline "succeeded".

Register once per machine: `docker run --privileged --rm tonistiigi/binfmt --install arm64`.
For a real change, build `--no-cache` and verify the image content
(`docker create` + `docker cp` the file out) before rolling the runtime.

## Bedrock Guardrail: topic policies hit the output too

A `topic_policy_config` DENY topic is evaluated against the **model response**, not
just the prompt. A broadly-worded "off_topic" topic ("anything not about
cybersecurity/compliance/...") blocked the agent's own answers — even "what is
control GOV-01?" and its capability overview — returning the guardrail's
blocked-output message for almost every request.

Fix: removed that topic. The guardrail keeps `PROMPT_ATTACK`, PII anonymisation,
and a narrow `harmful_security` topic (hacking / exploits / bypassing controls).
Off-topic misuse is handled by `_validate_input()` in `agent/main.py` and the
system prompt. `aws_bedrock_guardrail_version` has
`replace_triggered_by = [aws_bedrock_guardrail.scf_agent]` so a fresh immutable
version is cut on every edit and `GUARDRAIL_VERSION` on the runtime tracks it.

## A2A: async task model, not streaming

`message/send` is **non-blocking**. The bridge Lambda writes a `submitted` Task to
DynamoDB, enqueues `{task_id, prompt, runtime_session_id, context_id, caller}` on
SQS, and returns that Task in under a second — it never calls the runtime. An
SQS-triggered **worker Lambda** (`lambda/a2a_worker`, 600s timeout, event-source
`maximum_concurrency` cap) sets the Task `working`, calls `InvokeAgentRuntime`,
and writes `completed` (+ artifact) or `failed`. The client polls `tasks/get`
until the state is terminal. `tasks/cancel` conditionally marks a non-terminal
Task `canceled`; the worker's final write is conditional on `state <> "canceled"`.

Why: API Gateway HTTP API has a fixed ~30s integration timeout, so a synchronous
`message/send` returned `503`/`504` on any turn longer than that (the ISO 42001
query took 32s). The async model keeps the caller on sub-second requests only, so
turn length is bounded by the worker's 600s timeout instead. It also adds SQS
durability + DLQ (`maxReceiveCount` 2) and a concurrency cap on expensive Bedrock
runs, and it *is* the A2A `Task` lifecycle done properly. Implemented in
`terraform/a2a-async.tf`.

This is **not** incremental streaming — `capabilities.streaming = false`,
`message/stream` / `tasks/resubscribe` still return `-32004`, and the caller gets
the whole answer at once when the Task completes. Real SSE / token deltas need a
different client-facing transport (Function URL + Lambda Web Adapter, or Fargate +
ALB) because the Python managed Lambda runtime can't stream and API Gateway HTTP
APIs buffer + cap at 30s. Those options, and what token-level streaming
additionally needs from the agent container, are in
[`a2a-streaming.md`](a2a-streaming.md) — recorded so it's a decision later, not a
rediscovery.

## Two-phase apply for self-referential URLs

The A2A API and the frontend both need their own public URL baked into
configuration that is created in the same apply (Cognito callback URLs, the
container's `AUTH_REDIRECT_URI`, Agent Card `url`). Rather than a dependency cycle,
a `*_base_url` variable is left empty for the first apply and set to the
corresponding output for a second apply. Documented in each runbook.

## Summary of Key Lessons

1. **Use ECR containers for any agent with non-trivial dependencies** — The 30s
   init timeout for code deploy is too short for real-world packages.
2. **S3 Vectors is the simplest KB backend** — But you must pre-create the
   bucket/index and provide explicit ARNs.
3. **Bedrock's "unable to assume role" error is a catch-all** — Debug by trying
   the CLI directly and reading the actual sub-error.
4. **ARM64 cross-compilation is painful locally** — Register QEMU binfmt handlers,
   build `--no-cache`, and verify image content; plan for CI/CD on native ARM64.
5. **The Terraform AWS provider for AgentCore is new** — Expect rough edges,
   missing resources (connectors), and inconsistent state bugs; declare blocks the
   API returns even when they're "optional".
6. **Streamlit needs WebSockets** — App Runner can't host it; Fargate + ALB +
   CloudFront can, with no custom domain.
7. **Guardrail topic policies filter output** — keep DENY topics narrow or they
   block legitimate answers.
