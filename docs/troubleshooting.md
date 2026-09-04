# AgentCore Troubleshooting Playbook

A practical guide based on real issues encountered building this project.

## Before You Deploy Anything

1. **Run preflight** — Test the model ID can actually be invoked from your account
   ```powershell
   python scripts/preflight.py
   ```
2. **Verify ARM64** — If using containers, confirm `--platform linux/arm64` in your build
3. **Check inference profile** — Use `us.anthropic.*` not `anthropic.*` for on-demand models
4. **Confirm model access** — Model must be enabled in Bedrock console for your region

## Error Reference

### "Bedrock Knowledge Base was unable to assume the given role"

This is a catch-all error that means one of 5 things. Check in order:

| # | Actual Cause | Fix |
|---|---|---|
| 1 | S3 Vectors bucket/index doesn't exist | Create them before the KB. Empty `s3VectorsConfiguration` does NOT auto-create. |
| 2 | Role missing `s3vectors:QueryVectors` | Add `s3vectors:*` on the specific bucket/index ARN |
| 3 | Role missing `bedrock:ListFoundationModels` | Add alongside `bedrock:InvokeModel` |
| 4 | Trust policy missing conditions | Need both `aws:SourceAccount` AND `aws:SourceArn` with `knowledge-base/*` wildcard |
| 5 | IAM hasn't propagated yet | Add 15-30s `time_sleep` between role creation and KB creation |

**Debug tip:** Try the `create-knowledge-base` CLI call directly — the error response is more specific than Terraform's.

### "RuntimeClientError: Received error (500) from runtime"

The agent container crashed or returned an error. Check CloudWatch:

```powershell
aws logs filter-log-events `
  --log-group-name "/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT" `
  --start-time (Get-Date).AddMinutes(-5).ToUnixTimeMilliseconds() `
  --filter-pattern "ERROR" `
  --region us-east-1
```

| Symptom in logs | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: No module named 'strands'` | Dependencies not installed | Check Dockerfile pip install; ensure wheels are in the image |
| `ValidationException: Invocation of model ID ... not supported` | Wrong model ID format | Use inference profile: `us.anthropic.claude-sonnet-4-6` |
| `AccessDeniedException: not authorized to perform bedrock:InvokeModelWithResponseStream` | IAM missing permission | Add `bedrock:InvokeModel*` with `Resource: "*"` to runtime role |
| `ResourceNotFoundException: Model is marked as Legacy` | Model deprecated | Switch to a current inference profile |
| No logs at all | Container crashed before logging | Run locally: `docker run --platform linux/arm64 <image> python -c "import main"` |
| Server starts but no request log | Wrong endpoint paths | Must be `POST /invocations` and `GET /ping` (not `/` or `/health`) |

### "RuntimeClientError: Received error (502) from runtime"

Container returned invalid HTTP response.

- Check response is valid JSON with `Content-Type: application/json`
- Ensure `Content-Length` header matches actual body size
- Check for Python exceptions mid-response (crashed while writing)

### "Architecture incompatible for uri ... Supported platforms: [arm64]"

Container image is amd64 (x86). AgentCore requires ARM64.

```powershell
# Fix: build for ARM64
docker buildx build --platform linux/arm64 -t <ecr-url>:latest --push .

# Register the QEMU emulation handlers first (see next entry)
docker run --privileged --rm tonistiigi/binfmt --install arm64
```

### Cross-arch build "succeeds" but the runtime still runs old code

Symptoms: `agent/build-and-push.ps1` exits 0, `docker push` says *"Layer already
exists"* / the digest never changes, and the deployed agent behaves like the
previous image (e.g. a new env var / prompt / guardrail has no effect).

Cause: on an x86 host, `docker build --platform linux/arm64` needs QEMU `binfmt`
handlers. If they aren't registered, a `RUN` step fails with
`exec /bin/sh: exec format error` — and depending on cache state the build can
reuse the last good image instead of failing loudly.

Fix:
```powershell
docker run --privileged --rm tonistiigi/binfmt --install arm64
# verify:
docker run --rm --platform linux/arm64 arm64v8/busybox uname -m   # -> aarch64

# then rebuild WITHOUT cache and verify the content before rolling
docker build --no-cache --platform linux/arm64 -t <ecr-url>:latest agent/
$cid = docker create --platform linux/arm64 <ecr-url>:latest
docker cp "${cid}:/app/main.py" ./_check.py ; docker rm $cid
Select-String -Path ./_check.py -Pattern "GUARDRAIL_ID"   # expect a hit
docker push <ecr-url>:latest
.\update-runtime.ps1 -Region us-east-1
```

**Speed tip:** `--only-binary=:all:` in the Dockerfile keeps QEMU from compiling
native extensions (pydantic-core, cryptography), cutting the build from ~12 min to
~2-3 min.

### "Runtime initialization time exceeded (30s)"

Container takes too long to start responding to `/ping`.

| Deploy method | Cause | Fix |
|---|---|---|
| Code deploy (S3 zip) | pip install runs at init time, exceeds 30s | Switch to container with pre-baked dependencies |
| Container | Heavy imports at module level | Move all imports into a lazy-init function called on first request |

### "on-demand throughput isn't supported"

You used a raw model ID. Bedrock requires inference profiles for on-demand.

```
❌ anthropic.claude-sonnet-4-20250514-v1:0
✅ us.anthropic.claude-sonnet-4-6
```

Find available profiles:
```powershell
aws bedrock list-inference-profiles --region us-east-1 --query "inferenceProfileSummaries[?contains(inferenceProfileId,'claude')].inferenceProfileId"
```

### "Provider produced inconsistent result" (Terraform)

`aws_bedrockagentcore_gateway_target` HTTP targets: the API always returns a
`credential_provider_configuration { gateway_iam_role {} }` block; if the config
doesn't declare one, the provider errors on create and every later `plan` wants to
remove it.

**Fix (permanent):** declare the block so config matches the API —

```hcl
resource "aws_bedrockagentcore_gateway_target" "compliance_agent" {
  # ...
  credential_provider_configuration {
    gateway_iam_role {}
  }
}
```

This is already in `terraform/main.tf`. If you hit the error on a first apply from
an older revision, `terraform apply -refresh-only -auto-approve` clears the state
mismatch, then add the block.

### A2A route returns 401 Unauthorized

| Cause | Fix |
|---|---|
| Missing / expired / malformed `Authorization: Bearer` header | Get a fresh token; check `exp` |
| Token `iss` doesn't match the authorizer | Cognito: `https://cognito-idp.<region>.amazonaws.com/<pool-id>`. Entra v2: `https://login.microsoftonline.com/<tenant>/v2.0` (v1 tokens need `entra_issuer_override`) |
| Cognito M2M token has no `aud` | Expected — API Gateway matches `client_id` instead; both client IDs are listed as audiences. `terraform apply` again if you rotated a client |
| Calling `/entra/rpc` but `entra_tenant_id` was never set | That route/authorizer isn't created; set the var and re-apply |

The agent-card routes (`GET .../.well-known/agent-card.json`) are public — a 401
there means you hit `/rpc` by mistake.

### Hosted frontend: blank page / "loading" skeleton forever

Browser console shows `wss://.../\_stcore/stream failed`. Streamlit needs a
WebSocket.

- **AWS App Runner cannot host this** — it has no WebSocket support. The frontend
  runs on Fargate + ALB + CloudFront (`terraform/frontend.tf`).
- On the Fargate stack: check the ALB target group is `healthy` and CloudFront's
  origin request policy is `Managed-AllViewer` (so the `Upgrade`/`Connection`
  headers reach the task).
- `403 "Direct access is not allowed"` = you hit the ALB directly; use
  `terraform output -raw frontend_url` (CloudFront).

### `admin-create-user` doesn't email the temporary password

The user is created (`aws cognito-idp admin-list-users` shows them, status
`FORCE_CHANGE_PASSWORD`) but no email ever arrives — even with
`--desired-delivery-mediums EMAIL` and `--message-action RESEND`.

Two layered causes:

1. `--desired-delivery-mediums` defaults to `SMS` if omitted. With no `phone_number`
   attribute set, the invite has nowhere to go and is dropped silently; the command
   still returns success. Always pass `--desired-delivery-mediums EMAIL` explicitly.
2. **Even with that fixed, delivery can still silently fail.** This pool has no
   `email_configuration` block (check with
   `aws cognito-idp describe-user-pool --user-pool-id <id> --query UserPool.EmailConfiguration`) —
   it uses Cognito's shared `COGNITO_DEFAULT` sender, which AWS documents as
   testing-only: low quota, no bounce/delivery visibility, and mail from it gets
   filtered by a lot of providers. In practice this is unreliable enough that you
   should not depend on it for real users.

**Reliable fix — skip email, set the password directly:**

```powershell
aws cognito-idp admin-set-user-password --user-pool-id <pool-id> --username you@example.com `
  --password 'Some-Strong-Passw0rd!' --permanent --region us-east-1
```

This moves the user straight to `CONFIRMED` with no invite step at all — verify with
`admin-list-users` (`UserStatus: CONFIRMED`). Share the password with the user out of
band (Slack, phone, etc.).

**Durable fix for many users:** wire `email_configuration` on
`aws_cognito_user_pool.a2a` (`terraform/cognito-a2a.tf`) to Amazon SES (needs a verified
sending domain/address in `us-east-1`). Not set up in this project by default.

(Also worth knowing: `admin-create-user --message-action RESEND` only works while the
user is still `UNCONFIRMED`/`FORCE_CHANGE_PASSWORD` — it errors on a `CONFIRMED` user.)

### Agent refuses every question ("I cannot provide that type of response")

The Bedrock Guardrail is over-blocking. Bedrock **topic policies are evaluated
against the model output, not just the input**, so a broad "off-topic" DENY topic
flags the agent's own on-topic answers.

- Keep topic rules narrow (harmful/abuse only). Off-topic filtering belongs in
  `_validate_input()` + the system prompt.
- After editing `terraform/guardrails.tf`, a **new guardrail version** must be cut
  and the runtime env `GUARDRAIL_VERSION` bumped — the `replace_triggered_by` on
  `aws_bedrock_guardrail_version` handles this on `terraform apply`.
- Inspect what tripped: run the container with `LOG_LEVEL=DEBUG` and look for
  `topicPolicy` / `contentPolicy` / `assessment` with `"action":"BLOCKED"` in the
  guardrail trace.

### "Invalid Attribute Value Match" (Terraform naming)

AgentCore has inconsistent naming regex across resource types:

| Resource | Allowed | Pattern |
|---|---|---|
| `agent_runtime`, `memory` | Letters, numbers, underscores | `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` |
| `gateway`, `gateway_target` | Letters, numbers, hyphens | `^([0-9a-zA-Z][-]?){1,100}$` |

Use `replace(name, "-", "_")` for runtime/memory, keep hyphens for gateways.

### "Filterable metadata must have at most 2048 bytes" (KB ingestion)

S3 Vectors has a hard 2048-byte limit on metadata per indexed record.

- **Symptom:** `numberOfDocumentsFailed` is high in ingestion job stats
- **Cause:** Source documents are too large or have too many extractable fields
- **Fix:** Trim documents for KB indexing. Use DynamoDB for full data retrieval.

Check ingestion status:
```powershell
aws bedrock-agent list-ingestion-jobs --knowledge-base-id <kb-id> --data-source-id <ds-id> --region us-east-1
```

### Agent responds but with wrong/empty data

1. **KB returning nothing?** Check ingestion status — documents may have failed
2. **All documents failed?** S3 Vectors metadata limit. Use DynamoDB instead.
3. **DynamoDB empty?** Run `python scripts/load_dynamodb.py`
4. **Agent not calling tools?** Check system prompt tells it WHEN to use each tool

## General Debugging Order

```
1. Can I invoke the model directly?          → python scripts/preflight.py
2. Is the container image ARM64?             → Check ECR image details
3. Does the container start?                 → Look for /ping 200 in CloudWatch
4. Does it receive requests?                 → Look for /invocations logs
5. Does it call tools successfully?          → Check for tool errors in logs
6. Does the response get back to the client? → Check response size / timeout
```

## Useful Commands

```powershell
# Check runtime status
aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <id> --region us-east-1

# Tail runtime logs
aws logs tail "/aws/bedrock-agentcore/runtimes/<id>-DEFAULT" --follow --region us-east-1

# Check KB ingestion
aws bedrock-agent list-ingestion-jobs --knowledge-base-id <kb-id> --data-source-id <ds-id> --region us-east-1

# List available inference profiles
aws bedrock list-inference-profiles --region us-east-1 --query "inferenceProfileSummaries[].inferenceProfileId"

# Quick invocation test
$payload = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes('{"prompt":"hello"}'))
aws bedrock-agentcore invoke-agent-runtime --agent-runtime-arn <arn> --payload $payload --region us-east-1 response.bin
```
