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

The resource **was created successfully** — the error is the provider not
expecting the API to return a credential_provider block when none was specified.

**Workaround:** Run `terraform apply -refresh-only` after the first apply to
sync state. Subsequent applies work cleanly.

## Summary of Key Lessons

1. **Use ECR containers for any agent with non-trivial dependencies** — The 30s
   init timeout for code deploy is too short for real-world packages.
2. **S3 Vectors is the simplest KB backend** — But you must pre-create the
   bucket/index and provide explicit ARNs.
3. **Bedrock's "unable to assume role" error is a catch-all** — Debug by trying
   the CLI directly and reading the actual sub-error.
4. **ARM64 cross-compilation is painful locally** — Plan for CI/CD on native ARM64.
5. **The Terraform AWS provider for AgentCore is new** — Expect rough edges,
   missing resources (connectors), and inconsistent state bugs.
