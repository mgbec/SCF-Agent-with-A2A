# Acme HealthTech - Sample Organization for SCF Compliance Assessment

This is a fictional mid-sized healthcare SaaS company used to demonstrate
the SCF Compliance Agent's capabilities. It represents a realistic but
intentionally imperfect security posture with gaps for the agent to identify.

## Company Profile

- **Name:** Acme HealthTech Inc.
- **Industry:** Healthcare SaaS (B2B)
- **Size:** 175 employees (Medium Business, BLS Class 5-6)
- **Data Types:** PHI, PII, financial data
- **Infrastructure:** AWS-native, multi-region
- **Compliance Obligations:** HIPAA, SOC 2, HITRUST, state privacy laws (CA CCPA, NY SHIELD)
- **Current Frameworks:** Loosely aligned to NIST CSF 1.1 (not yet 2.0)

## How to Use

Feed the files in this directory to the SCF Compliance Agent with prompts like:

1. "Assess our security posture based on our current controls inventory"
2. "What gaps do we have for HIPAA compliance?"
3. "Evaluate our IAC domain maturity"
4. "Map our existing controls to EU NIS2 if we expand to Europe"
5. "What should we prioritize to get from CMM Level 2 to Level 3?"
6. "Assess our readiness for SOC 2 Type II"
7. "Review our incident response capabilities against SCF requirements"
8. "What quantum security controls should we start planning for?"

## Files

- `organization-profile.json` - Company metadata and context
- `controls-inventory.csv` - Current implemented controls with maturity self-assessment
- `infrastructure-summary.md` - AWS architecture and security tooling
- `policies-and-procedures.md` - Existing governance documentation status
- `recent-incidents.md` - Recent security events (for IR assessment)
- `third-party-vendors.md` - Key vendors and supply chain info
- `scan-prompts.md` - Ready-to-use prompts that showcase each agent capability
