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

# If QEMU not set up:
docker run --rm --privileged multiarch/qemu-user-static --reset -p yes
```

**Speed tip:** Use pre-downloaded ARM64 wheels in the Dockerfile to avoid QEMU pip compilation:
```dockerfile
COPY wheels/ /tmp/wheels/
RUN pip install --no-cache-dir --no-index --find-links=/tmp/wheels/ strands-agents boto3
```

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

Known bug in AWS provider 6.56 with `aws_bedrockagentcore_gateway_target` HTTP targets.

The resource **was created successfully** — it's a state sync issue.

```powershell
terraform apply -refresh-only -auto-approve
```

Subsequent applies work cleanly after this.

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
