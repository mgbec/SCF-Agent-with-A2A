# Deploying the Security Updates — Runbook

This runbook deploys the security hardening changes:

- **Bedrock Guardrail wiring** — the guardrail is now applied on every model
  call (runtime env vars + `bedrock:ApplyGuardrail` IAM + `BedrockModel` config).
- **Untrusted-content handling** — the agent system prompt now treats tool
  output (web search, stored answers, memory) as data, not instructions.
- **Frontend authentication** — the Streamlit UI requires OIDC login and
  attributes approvals to the verified identity.
- **Security smoke tests** — `scripts/test_agent.py` now asserts that attacks
  are blocked.
- **Repo hygiene** — log/response dumps removed from git tracking.

The changes span three deployment surfaces, and the order matters:

| # | Surface | What deploys it |
|---|---------|-----------------|
| 1 | Terraform infra (guardrail env vars, IAM, output) | `terraform apply` |
| 2 | Agent container (guardrail wiring + prompt in `agent/main.py`) | rebuild + push image, then roll the runtime |
| 3 | Frontend (local Streamlit auth) | local config only |

> **Why order matters:** the guardrail resource must exist before the runtime
> env vars can reference it, and the runtime pins the `:latest` image tag — so
> Terraform will **not** notice a freshly pushed image on its own. You have to
> roll the runtime explicitly (Step 4).

All commands assume PowerShell on Windows and use placeholders — `<account-id>`,
`<region>`, `<ecr-url>` — or read the real values from Terraform/CLI at runtime.
Never hardcode account IDs or ECR URLs into committed files.

---

## Step 0 — Preflight

```powershell
cd scripts
python preflight.py
```

Validates credentials, region, and model access before you change anything.

## Step 1 — Apply Terraform (creates the guardrail wiring)

```powershell
cd ..\terraform
terraform plan
```

Review the plan. You should see:

- `aws_bedrockagentcore_agent_runtime.compliance_agent` updated with two new
  environment variables: `GUARDRAIL_ID` and `GUARDRAIL_VERSION`.
- `aws_iam_role_policy.agentcore_bedrock` updated with an `ApplyGuardrail`
  statement.
- A new `guardrail_version` output.

If the guardrail resources aren't created yet, they'll appear as new
(`aws_bedrock_guardrail.scf_agent`, `aws_bedrock_guardrail_version.scf_agent`).

```powershell
terraform apply
```

At this point the **infrastructure** references the guardrail, but the
**running container** is still the old image. Continue to Step 2.

## Step 2 — Rebuild and push the agent container

The guardrail attachment and the untrusted-content system prompt live in
`agent/main.py`. They only take effect in a freshly built image.

```powershell
cd ..\agent
.\build-and-push.ps1 -Region <region>
```

`build-and-push.ps1` reads `ecr_repository_url` from Terraform and your account
ID from `aws sts get-caller-identity` — nothing is hardcoded. It authenticates
Docker to ECR, builds `linux/arm64` (required for Graviton), and pushes `:latest`.

To build, push, **and** roll the runtime in one step, add `-UpdateRuntime`
(this runs Step 4 for you):

```powershell
.\build-and-push.ps1 -Region <region> -UpdateRuntime
```

> **Cross-platform build note:** on an x86 machine the ARM64 build uses QEMU.
> Register the emulation handlers **once per machine** first, or `RUN` steps fail
> with `exec /bin/sh: exec format error` — and a cached build can silently reuse
> the old image so the "successful" push changes nothing:
>
> ```powershell
> docker run --privileged --rm tonistiigi/binfmt --install arm64
> docker run --rm --platform linux/arm64 arm64v8/busybox uname -m   # -> aarch64
> ```
>
> After a real code change, build `--no-cache` and confirm the new code is in the
> image before rolling:
>
> ```powershell
> docker build --no-cache --platform linux/arm64 -t (terraform -chdir=..\terraform output -raw ecr_repository_url):latest ..\agent
> $cid = docker create --platform linux/arm64 (terraform -chdir=..\terraform output -raw ecr_repository_url):latest
> docker cp "${cid}:/app/main.py" .\_check.py ; docker rm $cid
> Select-String .\_check.py -Pattern "GUARDRAIL_ID"   # expect a match; then remove _check.py
> ```
>
> `--only-binary` in the Dockerfile keeps QEMU from compiling native extensions
> (~2-3 min instead of 12+). See `deployment-decisions.md`.

## Step 3 — Verify the guardrail env vars are set (optional but recommended)

Confirm the runtime carries the guardrail configuration. Read the values from
Terraform rather than pasting them:

```powershell
cd ..\terraform
terraform output guardrail_id
terraform output guardrail_version
```

Both should return non-empty values. If `guardrail_id` is empty, Step 1 did not
complete and the agent will log a warning and run **without** a guardrail.

## Step 4 — Roll the runtime onto the new image

The runtime `container_uri` is pinned to `:latest` (a mutable tag), so a plain
`terraform apply` after pushing shows **no diff** and will not restart the
runtime on the new image. Force it explicitly. Pick one:

> **Permissions:** the principal running the deploy scripts needs
> `bedrock-agentcore:GetAgentRuntime` + `UpdateAgentRuntime` on the runtime,
> `iam:PassRole` on the runtime execution role, and ECR push permissions.
> Terraform provisions exactly this as a managed policy — attach it once to
> your IAM user or role:
>
> ```powershell
> $policyArn = terraform output -raw deploy_operator_policy_arn
> aws iam attach-user-policy --user-name <you> --policy-arn $policyArn
> # or: aws iam attach-role-policy --role-name <role> --policy-arn $policyArn
> ```
>
> Without these you'll get `AccessDeniedException` on `GetAgentRuntime`.

**Option A — `update-runtime.ps1` (recommended):**

```powershell
cd ..\agent
# First time: eyeball the assembled payload without changing anything
.\update-runtime.ps1 -Region <region> -DryRun
# Then apply for real
.\update-runtime.ps1 -Region <region>
```

`-DryRun` fetches the current runtime config, shows the image swap
(`before -> after`), prints each JSON argument (artifact, network, protocol,
env vars) and the exact `aws` command it would run — without calling
`update-agent-runtime`. Use it once to confirm the field names read back from
`get-agent-runtime` look right before performing the live update.

This reads the current runtime config via `get-agent-runtime`, swaps only the
container image URI, and sends it back via `update-agent-runtime` — preserving
the role, network mode, protocol, and env vars that Terraform provisioned
(including `GUARDRAIL_ID`/`GUARDRAIL_VERSION`). All identifiers are read from
Terraform outputs; nothing is hardcoded. You can also fold this into the push
by running `.\build-and-push.ps1 -UpdateRuntime`.

To deploy a specific immutable digest instead of the mutable tag:

```powershell
.\update-runtime.ps1 -ImageUri "<ecr-url>@sha256:<digest>"
```

**Option B — Terraform replace (single tool, but recreates the resource):**

```powershell
cd ..\terraform
terraform apply -replace="aws_bedrockagentcore_agent_runtime.compliance_agent"
```

New AgentCore sessions after the roll will use the new image. Existing idle
sessions time out per `idle_runtime_session_timeout` (300s).

> If you want to avoid this manual step in the future, pin the runtime to the
> image **digest** instead of `:latest` (e.g. resolve the digest after push and
> feed it into `container_uri`). Then `terraform apply` detects image changes
> automatically. That's a design change, not required for this deploy.

## Step 5 — Run the security + functional tests

```powershell
cd ..\scripts
python test_agent.py
```

The run includes a **SECURITY** group (prompt injection, jailbreak,
system-prompt exfiltration, off-topic misuse, harmful-security request, and
indirect/embedded injection). These pass only when the attack is **blocked or
refused**. If any `SEC:` test fails, the summary points you back to
`GUARDRAIL_ID` / `GUARDRAIL_VERSION` and confirms the guardrail is deployed.

A clean run means the guardrail is genuinely intercepting attacks end-to-end —
this is the verification the wiring in Steps 1–4 was for.

## Step 6 — Frontend authentication

The Streamlit frontend fails closed — with no OIDC login configured it renders no
page content. Both the app-level gate (`auth.py` `require_login()`) and the
approver-identity change apply whether you run it locally or hosted.

**Hosted (default):** `terraform apply` provisions the frontend on ECS Fargate +
ALB + CloudFront with its own Cognito client and SSM-backed secrets — no
`secrets.toml` to manage. First-time deploy (image bootstrap + the two-phase
`frontend_base_url` step) and user creation are in
[`frontend-deployment.md`](frontend-deployment.md). Nothing extra to do in this
runbook once `terraform apply` has run.

**Local run (optional):**

```powershell
cd ..\frontend
pip install -r requirements.txt

# One-time: create the git-ignored secrets file from the template
cp .streamlit\secrets.toml.example .streamlit\secrets.toml

# Generate a cookie secret and paste it into secrets.toml
python -c "import secrets; print(secrets.token_urlsafe(48))"

# Edit .streamlit\secrets.toml: client_id, client_secret, server_metadata_url,
# redirect_uri (see docs/frontend-deployment.md for the Cognito wiring).

streamlit run app.py
```

`.streamlit\secrets.toml` holds the OIDC client secret and is git-ignored —
commit only the `.example` template. For a hosted (ECS/CloudFront) deployment,
follow `docs/frontend-deployment.md`.

## Step 7 — Commit the changes

Stage the code and infra changes plus the git-hygiene cleanup. The log/response
dumps were removed from tracking (`git rm --cached`) and are now git-ignored.

```powershell
cd ..
git add .gitignore README.md `
  terraform/main.tf terraform/outputs.tf terraform/variables.tf `
  terraform/deploy-operator-policy.tf `
  agent/main.py agent/build-and-push.ps1 agent/update-runtime.ps1 `
  frontend/app.py frontend/auth.py frontend/requirements.txt `
  frontend/.streamlit/secrets.toml.example `
  frontend/pages/2_Approve_Answers.py `
  scripts/test_agent.py `
  docs/
git status   # confirm no secrets.toml, tfstate, tfvars, logs, or *.bin are staged
git commit -m "Wire Bedrock Guardrail, harden untrusted-content handling, add frontend auth + security tests"
```

Before committing, double-check the staged set excludes `terraform.tfvars`,
`*.tfstate`, `.streamlit/secrets.toml`, `logs*.txt`, `errs.txt`, and `*.bin` —
all of which are git-ignored.

---

## Rollback

- **Agent code / prompt:** re-push the previous image tag (or rebuild from the
  prior commit) and roll the runtime again (Step 4).
- **Guardrail:** removing `GUARDRAIL_ID`/`GUARDRAIL_VERSION` from the runtime env
  and re-applying makes the agent run without the guardrail (it logs a warning).
  The guardrail resource itself can stay.
- **Frontend:** stop the Streamlit process. Auth is local-only; nothing to roll
  back in the cloud.

## Verification checklist

- [ ] `terraform output guardrail_id` and `guardrail_version` return values
- [ ] New image pushed to ECR (`:latest`)
- [ ] Runtime rolled onto the new image (Step 4)
- [ ] `python test_agent.py` — all SECURITY tests PASS
- [ ] Frontend requires login; approvals record the signed-in identity
- [ ] `git status` shows no secrets/state/log files staged
