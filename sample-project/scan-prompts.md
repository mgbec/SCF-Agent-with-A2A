# SCF Compliance Agent - Demonstration Prompts

These prompts are designed to showcase each capability of the agent using
the Acme HealthTech sample project data. Feed the relevant context files
along with each prompt.

---

## 1. Full Compliance Assessment (Context: all files)

```
Based on the organization profile, controls inventory, infrastructure summary,
policies, incidents, and vendor information provided, perform a comprehensive
SCF 2026.2 compliance assessment for Acme HealthTech.

Identify:
- Overall maturity posture (estimated SCR-CMM level per domain)
- Top 10 highest-priority gaps
- Specific remediation recommendations sized for a 175-person healthcare SaaS company
- Areas of strength to build on
```

---

## 2. HIPAA Gap Analysis (Context: controls-inventory.csv + organization-profile.json)

```
Acme HealthTech is a HIPAA-covered entity processing ePHI. Using their controls
inventory, perform a gap analysis against HIPAA Security Rule requirements.

Their implemented SCF controls are:
GOV-01,GOV-01.1,GOV-02,GOV-04,GOV-06,GOV-15,AST-01,AST-02,AST-05,BCD-01,BCD-02,
CHG-01,CHG-02,CLD-01,CLD-02,CPL-01,CRY-01,CRY-03,CRY-05,DCH-01,END-01,END-08,
HRS-01,HRS-04,HRS-05,IAC-01,IAC-06,IAC-07,IAC-10,IAC-15,IAC-21,IRO-01,IRO-02,
IRO-04,MNT-01,MON-01,MON-02,NET-01,NET-02,NET-06,PES-01,PRI-01,PRI-03,SAT-01,
SEA-01,SEA-02,TDA-01,TDA-08,VPM-01,VPM-02,WEB-01

What are the gaps, prioritized by risk to PHI?
```

---

## 3. Maturity Assessment - Governance Domain (Context: policies-and-procedures.md + controls-inventory.csv)

```
Assess Acme HealthTech's maturity in the GOV (Security, Compliance & Resilience
Governance) domain against SCR-CMM Level 3 (Well Defined).

Current capabilities:
- CISO reports to CTO, has 6 dedicated security staff
- Information Security Policy exists (v3.1, current)
- Quarterly steering committee meetings (inconsistent attendance)
- GRC activities assigned to existing security staff, no dedicated GRC platform
- Some policies overdue for review
- No formal metrics/KPI program
- Risk management is informal

What specific criteria must they meet for Level 3, and where do they fall short?
```

---

## 4. AI Governance Gap Analysis (Context: organization-profile.json + infrastructure-summary.md)

```
Acme HealthTech runs CareFlow Analytics, an AI-powered clinical decision support
tool using LLM summarization, predictive models, and NLP extraction. They have:
- No formal AI governance policy
- No AI risk assessment framework
- Training data tracked in spreadsheets
- No model risk management framework
- No AI-specific access controls
- Bedrock (Claude) used for clinical summarization

Assess their gaps against the SCF AAT (Artificial Intelligence & Autonomous
Technologies) domain. What controls from AAT are critical for a healthcare AI
product, and what's their path to compliance?
```

---

## 5. EU Expansion Readiness (Context: organization-profile.json + controls-inventory.csv)

```
Acme HealthTech plans to expand to the EU in 2027. Assess their readiness against:
1. EU NIS2 Directive requirements
2. EU DORA (if they serve financial sector healthcare)
3. EU AI Act (for CareFlow Analytics)

Using their current SCF controls inventory, identify:
- Controls they already have that satisfy EU requirements
- New controls they must implement
- Timeline recommendations for a 2027 launch
```

---

## 6. Incident Response Maturity (Context: recent-incidents.md + controls-inventory.csv)

```
Review Acme HealthTech's incident response capabilities based on their recent
security events and current controls.

They report:
- 4 incidents in 12 months (1 high, 2 medium, 1 low)
- MTTD: 38 minutes (target: 15)
- MTTR: 2.5 hours (target: 1 hour)
- Only tabletop exercises, no purple team
- Post-incident reviews at 75% completion
- Missing playbooks for insider threat, supply chain, AI

Assess against SCF IRO domain controls and provide specific recommendations
to improve from their current Level 2 to Level 3.
```

---

## 7. Third-Party Risk Management (Context: third-party-vendors.md + controls-inventory.csv)

```
Acme HealthTech had a vendor breach (MailFlow) that exposed 12,000 patient
email addresses. Their current vendor management posture:
- TPM-01 (Third-Party Management): Partial implementation, Level 1
- TPM-03 (SCRM): Not implemented
- TPM-04 (Assessments): Partial, inconsistent

Using the vendor inventory provided, assess their third-party risk management
against SCF TPM domain requirements and recommend a program improvement plan
appropriate for a medium-sized healthcare company.
```

---

## 8. Quantum Readiness Assessment (Context: infrastructure-summary.md + controls-inventory.csv)

```
Acme HealthTech has QTS-01 (Quantum Risk Governance) marked as "Not Implemented"
with a 2027 roadmap note. They use:
- TLS 1.2+ for data in transit
- AES-256 for data at rest
- RSA 2048+ for key exchange
- AWS KMS for key management

Assess what the new SCF QTS (Quantum Security) domain requires and provide a
practical readiness roadmap for a medium healthcare SaaS company. What should
they start with in 2026?
```

---

## 9. SOC 2 Remediation (Context: organization-profile.json + controls-inventory.csv)

```
Acme HealthTech's most recent SOC 2 Type II audit had 2 exceptions:
1. Incomplete access review evidence (IAC-15 related)
2. Missing encryption-at-rest for legacy PostgreSQL database (CRY-05 related)

Additionally, their HITRUST assessment had a CAP for 4 vulnerability management
controls (VPM SLA compliance at 78%, target 95%).

For each finding:
- Map to specific SCF controls
- Identify the maturity gap
- Recommend specific remediation steps
- Estimate effort for a team of 6 security staff
```

---

## 10. Control Lookup & Cross-Framework Mapping (Context: none needed)

```
Look up SCF control IAC-15 (Account Management) and show me:
1. Full control description and assessment question
2. Maturity criteria for Levels 2 and 3
3. All framework mappings (NIST 800-53, ISO 27001, HIPAA, PCI DSS, NIS2, SOC 2)
4. Related risk and threat identifiers
5. Possible solutions for a medium-sized organization
```

---

## Tips for Best Results

- Provide the controls-inventory.csv when asking about gap analysis
- Include infrastructure-summary.md when asking about technical controls
- Include policies-and-procedures.md when asking about governance maturity
- Include recent-incidents.md when asking about IRO domain
- Include third-party-vendors.md when asking about TPM/SCRM
- Specify the organization size ("medium", 175 employees) for solution sizing
- Ask follow-up questions to drill deeper into specific domains or controls

---

## 11. Web Research - Regulatory Updates (Context: none needed)

```
Search for the latest HIPAA enforcement actions from HHS OCR in 2026.
Are there any recent cases involving access control failures or
unencrypted PHI that are relevant to Acme HealthTech's open findings?
```

---

## 12. Web Research - Vulnerability Intelligence (Context: infrastructure-summary.md)

```
Acme HealthTech runs EKS 1.29, Aurora PostgreSQL, and uses CrowdStrike Falcon.
Search for any critical CVEs or CISA KEV additions in 2026 that affect these
technologies. Cross-reference with SCF VPM domain controls to assess urgency.
```

---

## 13. Web Research - Best Practices for AI Governance (Context: organization-profile.json)

```
Acme HealthTech needs to establish an AI governance program for their clinical
decision support product. Search for current best practices and frameworks for
healthcare AI governance, then map recommendations to specific SCF AAT domain
controls they should implement.
```

---

## 14. Combined Analysis - Breach Case + Control Gap (Context: controls-inventory.csv)

```
Search for recent healthcare data breaches caused by third-party vendor
compromises (similar to Acme's MailFlow incident). What SCF controls would
have prevented or mitigated those breaches? Compare against Acme's current
TPM domain implementation.
```
