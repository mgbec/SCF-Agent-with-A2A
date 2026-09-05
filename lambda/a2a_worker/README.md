# a2a_worker Lambda

SQS-triggered worker that runs one A2A task to completion out of band from the
API Gateway request, so a long agent turn no longer hits API Gateway's ~30s
integration timeout.

- **Runtime:** `python3.13`, handler `worker.lambda_handler`, timeout
  `a2a_worker_timeout` (default 600s).
- **Dependencies:** none beyond the Lambda-provided `boto3`. Packaged by Terraform
  with `archive_file` straight from this directory — no build step.
- **Env:** `A2A_TASKS_TABLE`, `AGENT_RUNTIME_ARN`, `AGENT_RUNTIME_QUALIFIER`.
- **Trigger:** `aws_lambda_event_source_mapping` from the `scf-agent-a2a-tasks` SQS
  queue, `batch_size = 1`, `function_response_types = ["ReportBatchItemFailures"]`.
  The mapping's `scaling_config.maximum_concurrency` (`a2a_worker_max_concurrency`,
  default 5, min 2) caps concurrent Bedrock runs — reserved concurrency is *not*
  used, so it doesn't draw down the account's unreserved pool.
- **Failure handling:** a handled `InvokeAgentRuntime` error marks the task
  `failed` (error text in `status.message`) and consumes the message. An unhandled
  error propagates so SQS retries and, after `maxReceiveCount` (2), sends the
  message to `scf-agent-a2a-tasks-dlq`.
- **Cancel race:** the terminal write is conditional on `state <> "canceled"`, so a
  worker that finishes just after `tasks/cancel` logs a swallowed
  `ConditionalCheckFailedException` and leaves the task `canceled`.

The submitting side (`lambda/a2a_bridge/handler.py`) writes the `submitted` task
and enqueues; the client polls `tasks/get` on the bridge until the state is
terminal. See [`docs/a2a-integration.md`](../../docs/a2a-integration.md) and
[`docs/a2a-streaming.md`](../../docs/a2a-streaming.md).
