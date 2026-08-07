# Acme HealthTech - Policies & Procedures Inventory

## Governance Documentation Status

### Policies (Approved by Leadership)

| Policy | Version | Last Reviewed | Next Review | Status |
|--------|---------|---------------|-------------|--------|
| Information Security Policy | 3.1 | 2025-01-15 | 2026-01-15 | Current |
| Acceptable Use Policy | 2.4 | 2025-03-01 | 2026-03-01 | Current |
| Data Classification Policy | 2.0 | 2024-06-01 | 2025-06-01 | ⚠️ OVERDUE |
| Access Control Policy | 2.2 | 2025-05-01 | 2026-05-01 | Current |
| Incident Response Policy | 1.3 | 2024-09-01 | 2025-09-01 | ⚠️ OVERDUE |
| Business Continuity Policy | 1.1 | 2024-03-01 | 2025-03-01 | ⚠️ OVERDUE |
| Encryption Policy | 2.1 | 2025-08-01 | 2026-08-01 | Current |
| Change Management Policy | 2.0 | 2025-02-01 | 2026-02-01 | Current |
| Vendor Management Policy | 1.2 | 2024-11-01 | 2025-11-01 | ⚠️ OVERDUE |
| Privacy Policy (External) | 4.0 | 2025-07-01 | 2026-07-01 | Current |
| Employee Privacy Notice | 1.1 | 2025-01-01 | 2026-01-01 | Current |
| Remote Work Security Policy | 1.3 | 2025-04-01 | 2026-04-01 | Current |
| Mobile Device Policy | 1.0 | 2023-08-01 | 2024-08-01 | ⚠️ OVERDUE |

### Standards

| Standard | Status | Notes |
|----------|--------|-------|
| Password/Authentication Standard | Current | Aligned with NIST 800-63B |
| Network Security Standard | Current | Updated for ZTNA migration |
| Secure Development Standard | Current | OWASP aligned |
| Cloud Security Standard | Current | AWS Well-Architected aligned |
| Logging & Monitoring Standard | Current | Defines retention, alert SLAs |
| Cryptographic Standard | Current | TLS 1.2+, AES-256, RSA 2048+ |
| Data Retention Standard | ⚠️ Draft | Not yet approved. Retention inconsistent. |
| AI/ML Development Standard | ❌ Missing | No AI-specific security standard |
| Third-Party Security Standard | ❌ Missing | No standard for vendor assessment criteria |
| Quantum Cryptography Standard | ❌ Missing | Not started |

### Procedures (SOPs)

| Procedure | Status | Notes |
|-----------|--------|-------|
| Onboarding/Offboarding SOP | Current | Automated via Okta Workflows (80%) |
| Access Review SOP | Current | Quarterly. Execution gaps noted in SOC 2. |
| Incident Response Playbooks | Partial | 6 playbooks exist. Missing: insider threat, supply chain, AI-specific |
| Vulnerability Management SOP | Current | Defines SLAs. Execution at 78% compliance. |
| Change Management SOP | Current | Integrated with Jira + GitHub |
| Backup & Recovery SOP | Current | Tested annually |
| Penetration Testing SOP | Current | Annual scope definition + rules of engagement |
| Vendor Onboarding SOP | ⚠️ Outdated | Last updated 2023. No risk tiering. |
| Data Subject Access Request SOP | Current | Average response: 12 days (target: 30) |
| Security Exception Process | ❌ Missing | Exceptions handled informally |
| Risk Assessment SOP | ❌ Missing | No standardized methodology documented |
| Security Metrics Reporting SOP | ❌ Missing | Metrics reported ad-hoc to leadership |

## Observations

### Strengths
- Core operational security policies are current and well-maintained
- Development and change management procedures are mature
- Privacy documentation is current (driven by customer requirements)
- Technical standards align with industry frameworks

### Weaknesses
- 4 policies are overdue for review (Data Classification, IR, BCP, Vendor Mgmt)
- Several critical SOPs are missing entirely (risk assessment, exception handling, metrics)
- No AI governance documentation despite having AI products in production
- No quantum security or post-quantum migration planning
- Gap between documented procedures and actual execution (access reviews, vuln SLAs)
- Documentation is in SharePoint with manual version control (no automated tracking)
- No formal GRC platform for policy lifecycle management
