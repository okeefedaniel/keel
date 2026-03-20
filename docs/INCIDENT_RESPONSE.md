# DockLabs Incident Response Plan

**Version:** 1.0
**Effective Date:** March 2026
**Owner:** DockLabs Security Lead
**Review Frequency:** Annually or after any incident

## 1. Scope

This plan applies to all DockLabs products and infrastructure:
- Beacon CRM (beacon.docklabs.ai)
- Harbor Grants Management (harbor.docklabs.ai)
- Manifest Document Signing
- Keel Shared Platform
- Supporting infrastructure (Railway, AWS, GitHub, Microsoft Entra ID)

## 2. Severity Levels

| Level | Description | Response Time | Examples |
|-------|-------------|---------------|----------|
| **P1 — Critical** | Active data breach, system compromise, or data loss | Immediate (< 1 hour) | Unauthorized data access, malware infection, credential theft |
| **P2 — High** | Significant security vulnerability, service outage | < 4 hours | Unpatched critical CVE, brute-force attack in progress, DDoS |
| **P3 — Medium** | Security concern requiring investigation | < 24 hours | Suspicious login patterns, failed security scan, policy violation |
| **P4 — Low** | Minor security improvement needed | < 1 week | Configuration hardening, non-critical dependency update |

## 3. Roles and Responsibilities

| Role | Responsibility |
|------|---------------|
| **Security Lead** | Incident commander, coordinates response, makes escalation decisions |
| **Engineering Lead** | Technical investigation, containment, and remediation |
| **Product Owner** | Stakeholder communication, business impact assessment |
| **Legal/Compliance** | Regulatory notification, FOIA implications, breach notification |

## 4. Incident Response Phases

### Phase 1: Detection and Reporting
- **Automated:** Keel security monitoring (`check_security_events` command)
- **Manual:** Team member identifies suspicious activity
- **External:** Vulnerability report via security@docklabs.ai

**Action:** Log incident in the incident tracker with:
- Date/time of detection
- Who detected it
- Initial severity assessment
- Affected systems/products

### Phase 2: Assessment and Triage
1. Confirm the incident (rule out false positives)
2. Assign severity level (P1-P4)
3. Identify affected products and data
4. Determine if FOIA-classified data is involved
5. Activate response team based on severity

### Phase 3: Containment
**Immediate (P1/P2):**
- Isolate affected systems (disable network access, revoke credentials)
- Preserve evidence (snapshot databases, capture logs)
- Block malicious IPs via `KEEL_ADMIN_ALLOWED_IPS` or firewall rules
- Disable compromised user accounts

**Short-term:**
- Deploy emergency patches
- Rotate affected credentials and API keys
- Review audit logs for scope of compromise

### Phase 4: Eradication
- Remove root cause (patch vulnerability, remove malware)
- Verify fix with security testing
- Run `python manage.py security_audit --fail-on-error`
- Update WAF/firewall rules as needed

### Phase 5: Recovery
- Restore systems from verified clean backups
- Monitor for recurrence (enhanced logging for 30 days)
- Re-enable disabled accounts/services
- Verify data integrity

### Phase 6: Post-Incident Review
Within 5 business days of resolution:
- Document timeline of events
- Identify root cause
- List lessons learned
- Define preventive measures
- Update this plan if needed

## 5. Communication

### Internal Communication
- P1/P2: Immediate notification to all team members via Slack/Teams
- P3/P4: Notification at next standup or via email

### External Communication — State Agency Partners
- P1: Notify agency IT security contact within 4 hours
- P2: Notify within 24 hours
- P3/P4: Include in next scheduled security report

### External Communication — Affected Users
- Data breach affecting personal data: Notify within 72 hours per CT breach notification law (CT Gen. Stat. § 36a-701b)
- Include: What happened, what data was affected, what we're doing about it, what they should do

### Law Enforcement
- Contact local FBI field office for suspected criminal activity
- Preserve all evidence for potential forensic analysis
- Do not attempt to "hack back" or contact attackers

## 6. Connecticut-Specific Requirements

### FOIA Implications
If an incident involves FOIA-classified data:
- Notify the agency FOIA officer immediately
- Assess whether any FOIA responses were compromised
- Review zone boundaries (ensure Zone 2/3 data wasn't exposed to unauthorized parties)
- Document incident in FOIA audit trail

### CT Data Breach Notification (CT Gen. Stat. § 36a-701b)
Required notification if breach involves:
- Social Security numbers
- Driver's license numbers
- State ID numbers
- Financial account information
- Medical/health information

**Timeline:** Without unreasonable delay, generally within 60 days

## 7. Testing

- **Tabletop exercises:** Conduct annually with the full team
- **Penetration testing:** Schedule annually with a third-party firm
- **Security audit:** Run `python manage.py security_audit` weekly via CI/CD

## 8. Revision History

| Date | Version | Author | Changes |
|------|---------|--------|---------|
| 2026-03-20 | 1.0 | DockLabs | Initial release |
