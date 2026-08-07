# Acme HealthTech - Recent Security Events (Last 12 Months)

## Incident #INC-2025-041: Unauthorized Access Attempt via Stolen Credentials

- **Date:** 2025-10-12
- **Severity:** High
- **Status:** Resolved
- **Category:** Credential compromise

### Summary
An employee's corporate credentials were compromised via a phishing email that bypassed
the email security gateway. The attacker used the credentials to authenticate to Okta
from a TOR exit node. MFA blocked the initial login attempt, but the attacker then
executed an MFA fatigue attack (repeated push notifications). The employee eventually
approved a push after 12 attempts over 45 minutes.

### Impact
- Attacker accessed Slack, Confluence, and Jira for approximately 3 hours
- No PHI or production systems accessed (insufficient privileges)
- 4 internal architecture documents viewed in Confluence

### Detection
- GuardDuty flagged unusual geographic login after Okta session was established
- Alert reviewed by security team 47 minutes after initial access

### Response
- Account suspended within 15 minutes of alert review
- Full access log review completed in 2 hours
- Employee credentials rotated, hardware MFA token issued
- Incident closed after 3-day investigation

### Gaps Identified
- MFA fatigue attack not covered in awareness training
- No conditional access policy blocking TOR/VPN exit nodes
- Detection-to-response time: 47 minutes (target: 15 minutes)
- No SOAR playbook for automated credential suspension

---

## Incident #INC-2025-029: SSRF Vulnerability in Internal API

- **Date:** 2025-07-18
- **Severity:** Medium
- **Status:** Resolved
- **Category:** Application vulnerability (pen test finding)

### Summary
Annual penetration test discovered a Server-Side Request Forgery (SSRF) vulnerability
in an internal microservice API used for PDF report generation. The service accepted
URLs for chart image embedding without proper validation.

### Impact
- No evidence of exploitation in the wild
- Could have allowed access to EC2 metadata service (IMDSv1 still enabled on legacy instance)
- Potential for lateral movement to internal services

### Remediation
- Input validation added within 48 hours (emergency change)
- IMDSv2 enforced on all EC2 instances within 2 weeks
- URL allowlisting implemented for the PDF service

### Gaps Identified
- SSRF not in existing SAST rules at time of discovery
- IMDSv1 should have been disabled per cloud security standard (drift)
- No regular internal pen testing (only annual external)

---

## Incident #INC-2025-018: Third-Party Vendor Data Exposure

- **Date:** 2025-04-03
- **Severity:** Medium
- **Status:** Resolved
- **Category:** Supply chain / third-party risk

### Summary
A SaaS vendor used for customer communication (SendGrid competitor "MailFlow") disclosed
a breach affecting their platform. Acme HealthTech used MailFlow for appointment reminder
emails to patients. The breach potentially exposed email addresses and appointment
dates for patients.

### Impact
- ~12,000 patient email addresses + appointment dates potentially exposed
- No clinical data, SSN, or financial information involved
- Breach notification required under HIPAA (limited dataset)
- Notification sent to affected patients within 45 days

### Response
- Migrated to AWS SES within 2 weeks
- BAA with MailFlow reviewed - found to be outdated (2021 version)
- Breach notification filed with HHS OCR

### Gaps Identified
- MailFlow had not been assessed for security posture since initial onboarding (2021)
- BAA not updated to current template
- No ongoing monitoring of vendor security posture
- No tiering system to identify critical vendors
- Data flow mapping did not accurately reflect MailFlow's access to patient data

---

## Incident #INC-2025-008: Misconfigured S3 Bucket (Near Miss)

- **Date:** 2025-02-11
- **Severity:** Low (near miss)
- **Status:** Resolved
- **Category:** Misconfiguration

### Summary
AWS Config rule detected a new S3 bucket in the Development account that was created
without encryption and with overly permissive bucket policy (principal: *). The bucket
was created by a developer for a proof-of-concept and contained synthetic test data only.

### Impact
- No real data exposed (synthetic test data only)
- Bucket existed for 6 hours before auto-remediation

### Detection
- AWS Config non-compliant resource detected within 15 minutes
- Auto-remediation via Lambda applied encryption and restrictive policy
- Security team notified via SNS

### Gaps Identified
- SCPs should have prevented public bucket policies in all accounts
- Developer was unaware of encryption requirements (training gap)
- Sandbox account exists for this purpose but developer used dev account instead

---

## Summary Metrics (Last 12 Months)

| Metric | Value | Target |
|--------|-------|--------|
| Total security incidents | 4 | - |
| High severity incidents | 1 | 0 |
| Mean time to detect (MTTD) | 38 minutes | 15 minutes |
| Mean time to respond (MTTR) | 2.5 hours | 1 hour |
| Incidents involving PHI | 1 (vendor breach) | 0 |
| Breach notifications filed | 1 | 0 |
| Phishing simulation failure rate | 8.2% | <5% |
| Post-incident reviews completed | 3/4 (75%) | 100% |
| Findings from incidents tracked to resolution | 60% | 100% |
