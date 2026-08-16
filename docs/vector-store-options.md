# Vector Store Options & Evaluation Guide

## Current State

The Knowledge Base currently uses **S3 Vectors** as its vector store backend.
Due to a 2048-byte metadata limit per record, only ~7 of 1,534 SCF controls
successfully indexed. The system works around this limitation by using DynamoDB
for full data retrieval, with the KB providing limited semantic search.

## Why Upgrade the Vector Store?

| With S3 Vectors (current) | With OpenSearch Managed (upgrade) |
|---------------------------|----------------------------------|
| 7 controls indexed (~0.5%) | All 1,534 controls indexed (100%) |
| Agent relies on DynamoDB for everything | Agent uses KB for smart discovery, DynamoDB for detail |
| "Find controls related to encryption" returns nothing useful | Returns top 10 relevant controls ranked by semantic similarity |
| No benefit from RAG | Full RAG pipeline operational |
| Can't run meaningful evaluations | Can measure and improve retrieval quality |

## Vector Store Comparison

| Backend | Monthly Cost | Metadata Limit | Setup | Best For |
|---------|-------------|----------------|-------|----------|
| **S3 Vectors** (current) | ~$0 | 2KB ❌ | Easy | Tiny datasets |
| **OpenSearch Managed** (recommended) | ~$50 | None ✅ | Medium | Your use case |
| OpenSearch Serverless | ~$350 | None ✅ | Medium | High-scale production |
| Aurora pgvector | ~$30-60 | None ✅ | Medium | If you already run Aurora |
| Pinecone | $0 (free tier) | None ✅ | Easy | Data can leave AWS |
| Neptune Analytics | ~$150 | None ✅ | Complex | Graph + vector hybrid |

## Recommended: OpenSearch Managed Cluster

**Cost:** ~$50/month (t3.small.search, single node, 20GB EBS)

**What you get:**
- All 1,534 SCF controls fully indexed with complete text
- Semantic search: "encryption at rest healthcare" finds CRY-05, CRY-01, DCH-06
- Cross-framework discovery: "what maps to HIPAA access" finds IAC-01, IAC-06, IAC-15, IAC-21
- Maturity criteria searchable: "Level 3 governance" finds GOV domain controls
- Fast (<100ms) vector similarity search
- No silent ingestion failures

**How to enable:**
```powershell
# 1. Rename the Terraform file
cd terraform
Rename-Item opensearch-managed.tf.disabled opensearch-managed.tf

# 2. Update KB config in main.tf (swap S3 Vectors for OpenSearch Managed)
# 3. Apply
terraform apply

# 4. Create the vector index (see instructions in the .tf file)
# 5. Re-upload and ingest
cd ..\scripts
python reindex_kb.py
```

## Why You Need Evaluations

### The Problem Without Evals

Right now, when the agent answers a compliance question, you have no way to know:
- Did the KB return the **right** controls for the query?
- Did it **miss** important controls that should have been included?
- Is the model **hallucinating** information not in the retrieved data?
- Are the framework mappings **accurate** or fabricated?

In a compliance context, wrong answers have real consequences — failed audits,
regulatory fines, or false confidence in security posture.

### What Evaluations Measure

| Metric | What it tells you | Why it matters for compliance |
|--------|------------------|------------------------------|
| **Context Relevance** | Are the retrieved chunks actually about the topic? | Ensures gap analysis uses the right controls |
| **Context Recall** | Did the KB find ALL relevant chunks? | Catches missing controls (false negatives) |
| **Answer Correctness** | Is the final answer factually correct? | Prevents wrong framework mappings |
| **Faithfulness** | Does the model stick to retrieved data or hallucinate? | Critical — fabricated control IDs or mappings could mislead auditors |

### When to Run Evaluations

1. **After initial setup** — Baseline: does the system work at all?
2. **After SCF version updates** — Did new/changed controls break retrieval?
3. **After changing embedding models** — Does the new model retrieve better or worse?
4. **After changing chunking strategy** — Are smaller/larger chunks better for compliance data?
5. **Quarterly** — Ongoing quality assurance for a compliance tool

### How to Run a KB Evaluation

**Prerequisites:** OpenSearch Managed backend (S3 Vectors can't index enough data to evaluate meaningfully)

**Step 1: Create a test set** (50+ queries with expected results)

```json
[
  {
    "query": "What SCF controls address HIPAA access control requirements?",
    "expected_controls": ["IAC-01", "IAC-06", "IAC-15", "IAC-21", "IAC-10"],
    "expected_framework": "US HIPAA Security Rule / NIST SP 800-66 R2"
  },
  {
    "query": "Encryption at rest requirements",
    "expected_controls": ["CRY-05", "CRY-01"],
    "expected_framework": "multiple"
  },
  {
    "query": "Level 3 maturity for incident response",
    "expected_controls": ["IRO-01", "IRO-02", "IRO-04"],
    "expected_content": "SCR-CMM Level 3 Well Defined"
  }
]
```

**Step 2: Run the evaluation** via AWS Console or API

See: [Bedrock KB Evaluation Guide](https://docs.aws.amazon.com/bedrock/latest/userguide/knowledge-base-evaluation-create-ro.html)

**Step 3: Review metrics and iterate**

- If context recall is low → your chunking is too coarse, or embedding model misses domain terms
- If faithfulness is low → the model is hallucinating; add guardrails or constrain the prompt
- If answer correctness is low → retrieved chunks don't contain enough detail (trim less)

### Evaluation Cost

- Bedrock model invocations for the evaluation: ~$1-5 per run (50 queries)
- OpenSearch cluster running during eval: already included in $50/month
- **Total: ~$5 per evaluation run** — negligible for a compliance tool

### ROI of Evaluations

For a compliance agent, one wrong answer caught by evaluation is worth the entire cost:
- A missed HIPAA control in a gap analysis → potential $50K+ fine
- A hallucinated framework mapping → failed audit finding
- A false maturity score → misallocated remediation budget

Running evaluations quarterly costs ~$20/year. Not running them costs credibility.

## Migration Path

```
Current State                    Future State
─────────────                    ────────────
S3 Vectors (broken)              OpenSearch Managed ($50/month)
  ↓                                ↓
7/1,534 indexed                  1,534/1,534 indexed
  ↓                                ↓
KB search mostly useless         KB search fully functional
  ↓                                ↓
DynamoDB does everything         KB discovers → DynamoDB details
  ↓                                ↓
Can't run evals                  Run quarterly evals
  ↓                                ↓
No confidence in retrieval       Measured, tuned, auditable
```

The upgrade is a single Terraform rename + apply. No agent code changes needed —
the `search_scf_controls` tool already calls `bedrock:Retrieve` which works with
any KB backend.
