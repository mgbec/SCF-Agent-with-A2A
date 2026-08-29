# a2a_bridge Lambda

Terminates incoming [A2A protocol](https://a2a-protocol.org) traffic and forwards it to the
Bedrock AgentCore Runtime that hosts the SCF Compliance Agent.

- **Runtime:** `python3.13`, handler `handler.lambda_handler`
- **Dependencies:** none beyond the Lambda-provided `boto3`. Packaged by Terraform with
  `archive_file` straight from this directory — there is **no build step**.
- **Fronted by:** API Gateway HTTP API with per-route JWT authorizers (Cognito / Entra ID).
  The authorizer validates the token before this function runs.

Files:

| File | Purpose |
|------|---------|
| `handler.py` | Routing, JSON-RPC dispatch, A2A ⇄ AgentCore translation, task store |
| `agent_card.py` | Builds the per-route A2A AgentCard from environment variables |

Supported JSON-RPC methods: `message/send`, `message/stream` (buffered SSE), `tasks/get`,
`tasks/resubscribe`. `tasks/cancel` and `tasks/pushNotificationConfig/*` return standard
A2A "unsupported" errors because execution is synchronous.

See [`docs/a2a-integration.md`](../../docs/a2a-integration.md) for the full picture, auth
setup, and sample calls.
