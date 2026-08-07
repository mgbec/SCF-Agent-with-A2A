# Acme HealthTech - Infrastructure & Security Architecture

## Cloud Environment (AWS)

### Account Structure
- **Organization:** AWS Organizations with SCPs
- **Accounts:** 8 total
  - Management Account (billing + org management only)
  - Security Account (GuardDuty delegated admin, Security Hub, log archive)
  - Production (CareFlow Platform)
  - Production (CareFlow Analytics / ML)
  - Staging
  - Development
  - Shared Services (CI/CD, artifact repos, DNS)
  - Sandbox (experimentation, no PHI)

### Regions
- Primary: us-east-1 (N. Virginia)
- DR: us-west-2 (Oregon)
- No international regions (yet - EU expansion planned)

### Compute
- **EKS:** Primary workload platform (Kubernetes 1.29)
  - Production: 3 node groups, auto-scaling
  - Fargate for batch processing
- **Lambda:** Event-driven processing, API integrations
- **EC2:** Legacy PostgreSQL (1 instance, encrypted, migration planned Q2 2026)

### Data Stores
- **Aurora PostgreSQL:** Primary database (Multi-AZ, encrypted, automated backups)
- **DynamoDB:** Session state, caching
- **S3:** Object storage (encrypted, versioned, lifecycle policies)
- **ElastiCache Redis:** Application caching (in-transit encryption enabled)
- **Legacy PostgreSQL on EC2:** Patient demographics for 2 legacy clients
  - ⚠️ Encryption at rest: NOT enabled (SOC 2 exception, migration Q2 2026)

### Networking
- **VPCs:** Separate per account, peered where needed
- **Transit Gateway:** Hub-and-spoke between accounts
- **Security Groups:** Least-privilege, reviewed quarterly
- **NACLs:** Default deny inbound on sensitive subnets
- **WAF:** AWS WAF on ALBs with OWASP core rule set
- **CloudFront:** CDN for static assets (TLS 1.2 minimum)
- **VPN:** Deprecated. Replaced with Cloudflare ZTNA
- **PrivateLink:** Used for AWS service access from private subnets

### AI/ML Pipeline (CareFlow Analytics)
- **SageMaker:** Model training and hosting
- **Bedrock:** LLM integration for clinical summarization (Claude 3.5 Sonnet)
- **Data pipeline:** Glue ETL → S3 Data Lake → SageMaker
- **Model Registry:** SageMaker Model Registry
- ⚠️ No formal model risk management framework
- ⚠️ No AI-specific access controls beyond standard IAM
- ⚠️ Training data lineage tracked in spreadsheets

## Security Tooling

### Identity & Access
| Tool | Purpose | Coverage |
|------|---------|----------|
| Okta | SSO + MFA | 100% corporate apps |
| AWS IAM Identity Center | AWS console access | All accounts |
| CyberArk | Privileged Access Management | Infrastructure only |
| Okta Workflows | JML automation | 80% of systems |

### Detection & Monitoring
| Tool | Purpose | Coverage |
|------|---------|----------|
| Splunk Cloud | SIEM | All AWS logs + endpoint |
| AWS GuardDuty | Threat detection | All accounts |
| AWS Security Hub | Posture management | All accounts |
| CrowdStrike Falcon | EDR | All endpoints |
| AWS CloudTrail | Audit trail | All accounts, org trail |
| AWS Config | Configuration compliance | All accounts |

### Vulnerability Management
| Tool | Purpose | Coverage |
|------|---------|----------|
| Qualys VMDR | Infrastructure scanning | All EC2 + containers |
| Snyk | Dependency scanning | CI/CD pipelines |
| AWS Inspector | Container/EC2 scanning | Production accounts |
| Burp Suite Pro | DAST (manual) | Annual pen test |

### Data Protection
| Tool | Purpose | Coverage |
|------|---------|----------|
| AWS KMS | Key management | All encrypted services |
| AWS Macie | S3 data classification | Production S3 buckets |
| ⚠️ No DLP | - | Email + endpoints unmonitored |

### DevSecOps
| Tool | Purpose | Coverage |
|------|---------|----------|
| GitHub Advanced Security | SAST + secret scanning | All repos |
| Snyk | SCA | All repos |
| Checkov | IaC scanning | Terraform repos |
| Trivy | Container scanning | CI/CD |

## Known Infrastructure Gaps

1. **No DLP solution** - PHI could be exfiltrated via email/USB without detection
2. **Legacy unencrypted database** - 1 EC2 PostgreSQL instance (migration planned)
3. **Incomplete microsegmentation** - East-west traffic within EKS not fully controlled
4. **No network traffic analysis** - No NDR/NTA solution for lateral movement detection
5. **AI pipeline security** - No model poisoning detection, no adversarial testing
6. **DR validation** - RPO/RTO not validated with recent data volumes
7. **Alert fatigue** - Splunk generates ~200 alerts/day, team reviews ~40
8. **No SOAR** - Incident response is manual after initial detection
