# DockLabs Security Policy

**Effective Date:** March 2026
**Last Updated:** March 20, 2026
**Applies to:** All DockLabs products (Beacon CRM, Harbor, Manifest, and future products built on Keel)

## Reporting Security Vulnerabilities

If you discover a security vulnerability in any DockLabs product, please report it responsibly.

**Email:** security@docklabs.ai
**Response time:** We will acknowledge your report within 48 hours and provide a detailed response within 5 business days.

**Please include:**
- Description of the vulnerability
- Steps to reproduce
- Affected product(s) and version(s)
- Any potential impact assessment

**Please do NOT:**
- Publicly disclose the vulnerability before we've had a chance to address it
- Access, modify, or delete data belonging to other users
- Perform denial-of-service attacks

## Security Program Overview

### Standards and Frameworks
DockLabs security practices align with:
- **OWASP Top 10** — Web application security
- **NIST SP 800-53** — Security and privacy controls (where applicable to state government contracts)
- **CT State IT Policies** — Connecticut state information security requirements

### Authentication and Access Control
- **Single Sign-On (SSO):** Microsoft Entra ID (Azure AD) for state employee authentication
- **Multi-Factor Authentication (MFA):** TOTP and WebAuthn supported via django-allauth
- **Role-Based Access Control (RBAC):** Fine-grained role system with principle of least privilege
- **Session Management:** 1-hour session timeout, secure and HttpOnly cookies, SameSite=Lax

### Data Protection
- **Encryption in Transit:** TLS 1.2+ enforced via HSTS (1 year with preload)
- **Encryption at Rest:** Database encryption via managed cloud provider (AWS/Railway PostgreSQL)
- **Data Classification:** Three-zone FOIA-aware architecture (Shared, Agency Internal, Partner Private)
- **File Upload Scanning:** ClamAV malware scanning for all uploaded files

### Audit and Monitoring
- **Audit Logging:** Every user action logged with timestamp, IP address, user identity, and change details
- **Security Event Monitoring:** Automated detection of brute-force attempts, bulk exports, and after-hours admin access
- **Log Retention:** Audit logs retained per data retention policy (minimum 7 years for standard records)

### Infrastructure
- **Hosting:** Railway (development/staging), AWS GovCloud (production)
- **Database:** PostgreSQL with managed backups
- **Static Assets:** WhiteNoise with content-type validation
- **CI/CD:** GitHub Actions with automated security scanning (Bandit, Safety)

### Incident Response
See [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) for our full incident response plan.

### Employee Security
- Security awareness training conducted annually
- Background checks for personnel with access to sensitive systems
- Access revocation within 24 hours of role change or termination

## Compliance

### Connecticut FOIA (Freedom of Information Act)
DockLabs products that handle state data implement full FOIA compliance:
- Zone-based data classification
- Attorney review workflows
- Statutory exemption tracking
- Complete audit trail for FOIA request lifecycle

### Data Retention
- Standard records: 7 years
- Extended records: 10 years
- Permanent records: Retained indefinitely
- FOIA records: Retained per CT statutory requirements

## Contact

For security concerns: **security@docklabs.ai**
For general inquiries: **support@docklabs.ai**
