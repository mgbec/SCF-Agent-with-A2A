# SCF Compliance Agent - Bedrock AgentCore + Terraform

An agentic compliance workflow powered by Amazon Bedrock AgentCore that provides
AI-driven Secure Controls Framework (SCF) 2026.2 compliance assessment,
gap analysis, and remediation guidance.

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    SCF Compliance Agent                            │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  ┌───────────────┐   ┌───────────────┐   ┌──────────────────┐   │
│  │ AgentCore     │   │  Bedrock      │   │  AgentCore       │   │
│  │ Runtime       │◄──│  Knowledge    │   │  Memory          │   │
│  │ (Agent Code)  │   │  Base (SCF)   │   │  (Sessions)      │   │
│  └──────┬────────┘   └───────────────┘   └──────────────────┘   │
│         │                                                         │
│  ┌──────┴────────┐   ┌───────────────┐   ┌──────────────────┐   │
│  │ MCP Gateway   │   │  Web Search   │   │  Bedrock FM      │   │
│  │ (IAM Auth)    │──►│  Connector    │   │  (Claude)        │   │
│  └───────────────┘   │  (Live Web)   │   └──────────────────┘   │
│                       └───────────────┘                           │
│  ┌───────────────┐   ┌───────────────┐   ┌──────────────────┐   │
│  │ HTTP Gateway  │   │  S3 Bucket    │   │  Auto-Updater    │   │
│  │ (Agent Route) │   │  (SCF JSON)   │   │  (Lambda+EB)     │   │
│  └───────────────┘   └───────────────┘   └──────────────────┘   │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

## What It Does

1. **Control Lookup** - Query any of 1,534 SCF controls by ID, domain, or keyword
2. **Framework Mapping** - Map between SCF and 252+ regulations (HIPAA, SOX, PCI DSS, NIS2, etc.)
3. **Maturity Assessment** - Assess organizational maturity (SCR-CMM Levels 0-5)
4. **Gap Analysis** - Identify gaps against target frameworks with remediation guidance
5. **Compliance Scoping** - Filter controls by profile (ESP Level 1/2/3, AI, MA&D)
6. **Risk & Threat Correlation** - Link controls to risk scenarios and threats
7. **Web Research** (live internet via Bedrock AgentCore Web Search):
   - Latest regulatory updates and enforcement actions
   - Current CVE/vulnerability intelligence (NVD, CISA KEV)
   - Recent breach cases and outcomes
   - Industry best practices and implementation guides

### Data Source Strategy

| Source | Role | When Used |
|--------|------|-----------|
| S3 + Bedrock Knowledge Base (S3 Vectors) | Authoritative SCF control data | Control lookups, mappings, maturity criteria, gap analysis |
| Bedrock AgentCore Web Search | Supplementary current context | Regulatory updates, CVE intel, breach cases, best practices |

The Knowledge Base uses **S3 Vectors** as its storage backend — Bedrock manages the
vector index automatically. No OpenSearch cluster or collection to maintain. Your
SCF JSON lives in S3, and Bedrock handles embedding and retrieval.

### Auto-Update Pipeline

The SCF data stays current via a serverless pipeline:

- **EventBridge** triggers a Lambda every Monday at 8:00 UTC
- **Lambda** downloads the latest SCF JSON, compares version against SSM parameter
- If a new version exists: uploads to S3, triggers KB re-ingestion, notifies via SNS
- **SSM Parameter Store** tracks the deployed version
- **S3 versioning** keeps historical copies for rollback

No manual intervention required — your team gets an email when the data updates.

## Prerequisites

- Terraform >= 1.6
- AWS CLI v2 configured with credentials
- Docker (for building the agent container)
- Python 3.13+ (for agent code development)
- Access to Amazon Bedrock (Claude model enabled in your region)
- AgentCore access enabled in your account

## Quick Start

```powershell
# 1. Initialize Terraform
cd terraform
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your region, model, and notification email

terraform init
terraform plan
terraform apply

# 2. Upload SCF data to S3 and sync the Knowledge Base
cd ..\scripts
python upload_scf_data.py

# 3. Build and push the agent container
cd ..\agent
.\build-and-push.ps1

# 4. Test the agent
cd ..\scripts
python test_agent.py
```

## Project Structure

```
scf-compliance-agent/
├── README.md
├── .gitignore
├── terraform/
│   ├── main.tf                 # Core infra (KB, Runtime, Gateway, S3, ECR, IAM)
│   ├── scf-updater.tf         # Auto-update pipeline (Lambda, EventBridge, SNS)
│   ├── variables.tf            # Input variables
│   ├── outputs.tf              # Output values
│   ├── terraform.tfvars.example
│   └── backend.tf.example      # Remote state config template
├── agent/
│   ├── main.py                 # Agent entry point (Strands Agents framework)
│   ├── tools/
│   │   ├── scf_lookup.py      # Control lookup by ID, domain, keyword
│   │   ├── framework_mapper.py # Cross-framework mapping (252+ frameworks)
│   │   ├── maturity_assessor.py # SCR-CMM Level 0-5 assessment
│   │   ├── gap_analyzer.py    # Gap analysis + remediation guidance
│   │   └── web_research.py    # Live web search (regulatory, CVE, breaches)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── build-and-push.ps1
├── lambda/
│   └── scf_updater/
│       └── handler.py          # Weekly SCF version check + update
├── scripts/
│   ├── upload_scf_data.py      # Initial data load to S3
│   └── test_agent.py           # Integration test suite
└── sample-project/             # Fictional company for demos (Acme HealthTech)
    ├── organization-profile.json
    ├── controls-inventory.csv
    ├── infrastructure-summary.md
    ├── policies-and-procedures.md
    ├── recent-incidents.md
    ├── third-party-vendors.md
    └── scan-prompts.md         # 14 ready-to-use demo prompts
```

## Infrastructure Components

| Resource | Type | Purpose |
|----------|------|---------|
| S3 Bucket | `aws_s3_bucket` | Stores SCF JSON source data |
| Bedrock Knowledge Base | `aws_bedrockagent_knowledge_base` | Vector-indexed SCF controls (S3 Vectors backend) |
| AgentCore Runtime | `aws_bedrockagentcore_agent_runtime` | Hosts the compliance agent container |
| AgentCore Memory | `aws_bedrockagentcore_memory` | Persists assessment sessions (90-day TTL) |
| MCP Gateway | `aws_bedrockagentcore_gateway` | Exposes Web Search connector via MCP |
| HTTP Gateway | `aws_bedrockagentcore_gateway` | Routes traffic to the agent runtime |
| Web Search Target | CLI provisioner | Bedrock managed web search connector |
| ECR Repository | `aws_ecr_repository` | Agent container images |
| Lambda Function | `aws_lambda_function` | Weekly SCF version checker/updater |
| EventBridge Rule | `aws_cloudwatch_event_rule` | Cron trigger (Mondays 8:00 UTC) |
| SNS Topic | `aws_sns_topic` | Update notifications to your team |
| SSM Parameter | `aws_ssm_parameter` | Tracks deployed SCF version |

## Configuration

### Required Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `aws_region` | AWS region (must have Bedrock + AgentCore) | `us-east-1` |
| `project_name` | Prefix for all resource names | `scf-agent` |
| `bedrock_model_id` | FM for agent reasoning | `anthropic.claude-sonnet-4-20250514-v1:0` |
| `embedding_model_id` | Embedding model for KB vectors | `amazon.titan-embed-text-v2:0` |

### Optional Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `log_level` | Agent log level (DEBUG/INFO/WARNING/ERROR) | `INFO` |
| `notification_email` | Email for SCF update alerts | `""` (disabled) |

## Naming Conventions

AgentCore resources have inconsistent naming rules across resource types:

| Resource Type | Allowed Characters | Pattern |
|---------------|-------------------|---------|
| Runtime, Memory | Letters, numbers, underscores | `^[a-zA-Z][a-zA-Z0-9_]{0,47}$` |
| Gateway, Gateway Target | Letters, numbers, hyphens | `^([0-9a-zA-Z][-]?){1,100}$` |
| IAM, S3, ECR, Lambda | Standard AWS naming | Hyphens allowed |

The Terraform handles this automatically using `replace()` where needed.

## Sample Project

The `sample-project/` directory contains a fictional company (**Acme HealthTech** —
175-employee healthcare SaaS) with realistic security posture data and intentional
gaps for the agent to discover. See `sample-project/scan-prompts.md` for 14
ready-to-use prompts that exercise every agent capability.

## Costs

Approximate monthly costs when idle (no active assessments):

| Service | Cost | Notes |
|---------|------|-------|
| S3 (SCF data) | ~$0.01 | <100MB stored |
| Bedrock KB (S3 Vectors) | ~$0.00 | Charged per query, not storage |
| AgentCore Runtime | $0 when idle | Pay-per-session (microVM) |
| AgentCore Memory | ~$0.00 | Charged per operation |
| Lambda (updater) | ~$0.00 | 4 invocations/month |
| Web Search | Per-query | Charged when agent searches |
| Bedrock FM (Claude) | Per-token | Charged per assessment |

Active usage costs depend on assessment volume and conversation length.

## Cleanup

```powershell
cd terraform
terraform destroy
```

Note: The Web Search gateway target created via CLI will need manual deletion
if `terraform destroy` doesn't catch it:

```powershell
aws bedrock-agentcore-control delete-gateway-target `
  --gateway-identifier <gateway-id> `
  --target-id <target-id> `
  --region us-east-1
```
