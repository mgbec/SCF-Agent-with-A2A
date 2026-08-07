# Acme HealthTech - Third-Party Vendor Inventory

## Critical Vendors (Access to PHI/Production Systems)

| Vendor | Service | Data Access | BAA | Last Assessment | Risk Tier |
|--------|---------|-------------|-----|-----------------|-----------|
| AWS | Cloud Infrastructure | All data (platform) | Yes (2025) | N/A (hyperscaler) | Critical |
| Okta | Identity & SSO | Auth data, user directory | Yes (2025) | SOC 2 reviewed 2025 | Critical |
| CrowdStrike | EDR | Endpoint telemetry | Yes (2024) | SOC 2 reviewed 2024 | Critical |
| Splunk | SIEM | All log data | Yes (2024) | SOC 2 reviewed 2024 | High |
| Qualys | Vulnerability Mgmt | Asset inventory, vulns | DPA (2024) | SOC 2 reviewed 2024 | High |
| CyberArk | PAM | Privileged credentials | Yes (2025) | SOC 2 reviewed 2025 | Critical |
| ServiceNow | ITSM/CMDB | Asset metadata | DPA (2023) | ⚠️ Not assessed since 2023 | High |

## High-Importance Vendors

| Vendor | Service | Data Access | BAA | Last Assessment | Risk Tier |
|--------|---------|-------------|-----|-----------------|-----------|
| GitHub | Source Code | Source code, secrets (scanned) | DPA (2024) | SOC 2 reviewed 2025 | High |
| Snyk | SCA/SAST | Code metadata | DPA (2024) | SOC 2 available | Medium |
| Cloudflare | ZTNA/CDN | Network metadata | DPA (2024) | SOC 2 reviewed 2024 | High |
| KnowBe4 | Security Awareness | Employee emails + training data | DPA (2023) | ⚠️ Not assessed since onboard | Medium |
| PagerDuty | Alerting | Alert metadata | DPA (2024) | SOC 2 available | Medium |
| Jira/Atlassian | Project Management | Incident tickets, project data | DPA (2024) | SOC 2 reviewed 2024 | Medium |

## Data Sub-Processors (Access PHI on Behalf of Customers)

| Vendor | Service | Data Access | BAA | Last Assessment | Risk Tier |
|--------|---------|-------------|-----|-----------------|-----------|
| AWS SES | Email (transactional) | Patient email + appointment | Yes (AWS) | N/A (AWS service) | High |
| Twilio | SMS notifications | Patient phone + appointment | Yes (2025) | SOC 2 reviewed 2025 | High |
| ~~MailFlow~~ | ~~Email~~ | ~~Patient email~~ | ~~Outdated~~ | ~~Breached~~ | ⛔ Decommissioned |

## Software Supply Chain

### Open Source Dependencies (Top Risk)
- **Total dependencies:** ~1,200 (direct + transitive)
- **Dependency scanning:** Snyk in CI/CD (blocks critical/high)
- **SBOM generated:** Yes (CycloneDX format, per build)
- **SBOM shared with customers:** On request only
- **Known vulnerable dependencies:** 3 medium (remediation in backlog)

### Container Base Images
- **Base images:** AWS-managed ECR public images (Amazon Linux 2023)
- **Image scanning:** Trivy + AWS Inspector
- **Image signing:** ❌ Not implemented
- **Admission control:** ❌ No image policy enforcement in EKS

## Gaps & Concerns

1. **No formal vendor tiering** - Risk tiers shown above are informal, not documented in policy
2. **Inconsistent assessment cadence** - Some vendors not reassessed since onboarding
3. **BAA currency** - ServiceNow BAA is from 2023, likely needs updating
4. **No ongoing monitoring** - No vendor risk monitoring platform (SecurityScorecard, BitSight, etc.)
5. **SBOM not proactively shared** - Customers increasingly requesting this
6. **No container image signing** - Can't verify supply chain integrity at deployment
7. **No fourth-party visibility** - Don't track vendors' sub-processors systematically
8. **No SCRM program** - No formal supply chain risk management per SCF TPM-03
9. **Incident notification** - MailFlow breach showed gap in vendor incident notification SLAs
10. **Concentration risk** - Heavy AWS dependency with no multi-cloud contingency
