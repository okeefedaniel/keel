# Keel — DockLabs Shared Platform

Shared Django infrastructure for DockLabs products (Beacon, Harbor, Manifest).

## Install

```bash
pip install git+https://github.com/okeefedaniel/keel.git
```

Add to `requirements.txt`:
```
git+https://github.com/okeefedaniel/keel.git
```

## What's Included

### keel.core
- **AbstractAgency, AbstractAuditLog, AbstractNotification, AbstractArchivedRecord** — Abstract base models
- **WorkflowEngine** — Declarative status-transition system with role guards
- **AuditMiddleware** — Request IP extraction + login audit logging
- **ZoneFormMixin** — FOIA zone-aware form field filtering
- **SortableListMixin, AgencyObjectMixin** — Reusable view mixins
- **safe_redirect_url, rate_limit** — Security utilities
- **KeelSSOAdapter** — Configurable Microsoft Entra ID SSO adapter

### keel.security
- **SecurityHeadersMiddleware** — CSP, Permissions-Policy, COOP headers
- **FailedLoginMonitor** — Brute-force detection with automatic IP lockout
- **AdminIPAllowlistMiddleware** — Restrict /admin/ to allowed IPs/networks
- **File scanning** — ClamAV malware detection + extension/size validation
- **Security alerts** — Automated suspicious activity detection + email/webhook notifications
- **Compliance audit** — `security_audit` management command for CI/CD
- **Security event monitor** — `check_security_events` management command for cron

### keel.foia
- **Abstract FOIA models** — FOIARequest, FOIAScope, FOIASearchResult, FOIADetermination, FOIAResponsePackage, FOIAAppeal
- **FOIA search engine** — Zone-aware record search across models
- **FOIA workflow** — Status transitions for request lifecycle
- **AI review** — Claude-powered pre-classification of search results

### docs/
- **SECURITY.md** — Vulnerability disclosure policy and security program overview (copy to each product repo)
- **INCIDENT_RESPONSE.md** — Full incident response plan with CT-specific requirements

### .github/workflows/
- **security.yml** — Reusable CI/CD security scanning (Bandit, Safety, secrets detection)

---

## Integration Guide

This section is written for Claude Code (or any developer) integrating Keel into a DockLabs product. Follow each section in order.

### Step 1: Add Keel Dependency

Add to `requirements.txt`:
```
git+https://github.com/okeefedaniel/keel.git
```

Then install:
```bash
pip install -r requirements.txt
```

### Step 2: Register Keel Apps in settings.py

Add `keel.security` to `INSTALLED_APPS` (this registers the management commands):

```python
INSTALLED_APPS = [
    # ... Django built-ins ...
    'keel.security',
    # ... your product apps ...
]
```

> **Note:** `keel.core` and `keel.foia` provide abstract models and utilities — they do NOT need to be in `INSTALLED_APPS` unless you want their management commands. Import from them directly.

### Step 3: Add Security Middleware

Add these to `MIDDLEWARE` in `settings.py`, in this order:

```python
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'keel.security.middleware.SecurityHeadersMiddleware',  # <-- ADD after SecurityMiddleware
    'keel.security.middleware.FailedLoginMonitor',         # <-- ADD after SecurityHeaders
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    # ... rest of middleware ...
    'keel.core.middleware.AuditMiddleware',                 # <-- ADD at end (replaces local copy)
]
```

Optional — restrict `/admin/` to specific IPs:
```python
# Add after FailedLoginMonitor:
'keel.security.middleware.AdminIPAllowlistMiddleware',
```

### Step 4: Add Keel Settings

Add these settings to `settings.py`:

```python
# ---------------------------------------------------------------------------
# Keel Configuration
# ---------------------------------------------------------------------------

# Tell Keel which AuditLog model to use (your product's concrete model)
KEEL_AUDIT_LOG_MODEL = 'core.AuditLog'

# Security alert recipients (receives email on suspicious activity)
KEEL_SECURITY_ALERT_RECIPIENTS = [
    os.environ.get('SECURITY_ALERT_EMAIL', 'security@docklabs.ai'),
]

# Optional: Slack/Teams webhook for security alerts
# KEEL_SECURITY_ALERT_WEBHOOK = os.environ.get('SECURITY_ALERT_WEBHOOK', '')

# File upload security
KEEL_FILE_SCANNING_ENABLED = not DEBUG  # ClamAV scanning in production
KEEL_CLAMAV_SOCKET = os.environ.get('CLAMAV_SOCKET', '/var/run/clamav/clamd.ctl')
KEEL_CLAMAV_FAIL_CLOSED = True  # reject uploads if scanner is unavailable
KEEL_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
KEEL_ALLOWED_UPLOAD_EXTENSIONS = [
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.rtf',
    '.odt', '.ods', '.ppt', '.pptx',
    '.png', '.jpg', '.jpeg', '.gif', '.tiff', '.svg',
    '.zip', '.gz', '.tar',
]

# Failed login lockout
KEEL_LOGIN_MAX_FAILURES = 10          # max failures before lockout
KEEL_LOGIN_LOCKOUT_WINDOW = 900       # 15 minutes window
KEEL_LOGIN_LOCKOUT_DURATION = 1800    # 30 minutes lockout
KEEL_LOGIN_PATHS = ['/auth/login/', '/accounts/login/', '/admin/login/']

# Optional: restrict /admin/ to specific IPs
# KEEL_ADMIN_ALLOWED_IPS = ['10.0.0.0/8', '192.168.0.0/16']

# Business hours for after-hours admin alerts (24h format, local timezone)
KEEL_BUSINESS_HOURS = (8, 18)  # 8am-6pm

# Product name (used in alert emails)
KEEL_PRODUCT_NAME = 'Beacon CRM'  # change per product

# Content Security Policy (optional — customize per product)
# KEEL_CSP_POLICY = "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net https://unpkg.com; style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com https://cdn.jsdelivr.net; img-src 'self' data: https:; connect-src 'self'"
```

### Step 5: Extend Abstract Models (if not already done)

If your product has its own `AuditLog`, `Notification`, etc., make them extend Keel's abstract bases. **No migration is needed** if the fields are identical.

```python
# core/models.py
from keel.core.models import AbstractAuditLog, AbstractNotification, AbstractArchivedRecord

class AuditLog(AbstractAuditLog):
    """Product-specific audit log. Add extra Action choices here."""
    class Action(AbstractAuditLog.Action):
        FOIA_SEARCH = 'foia_search', 'FOIA Search'
        FOIA_DETERMINATION = 'foia_determination', 'FOIA Determination'

    class Meta(AbstractAuditLog.Meta):
        pass

class Notification(AbstractNotification):
    class Meta(AbstractNotification.Meta):
        pass

class ArchivedRecord(AbstractArchivedRecord):
    class Meta(AbstractArchivedRecord.Meta):
        pass
```

### Step 6: Replace Local Duplicates

These files in your product are duplicates of Keel code. Replace their contents with imports:

**`core/middleware.py`** — replace with:
```python
# Audit middleware is now provided by Keel.
# Configure KEEL_AUDIT_LOG_MODEL in settings.py.
from keel.core.middleware import AuditMiddleware  # noqa: F401
```

**`core/utils.py`** — replace with:
```python
from keel.core.utils import safe_redirect_url, rate_limit  # noqa: F401
# Add any product-specific utilities below.
```

**`core/workflow.py`** — keep your product-specific workflows, but import the engine from Keel:
```python
from keel.core.workflow import Transition, WorkflowEngine  # noqa: F401

# Product-specific workflows below...
COMPANY_APPROVAL_WORKFLOW = WorkflowEngine([
    Transition('pending', 'approved', roles=['company_moderator'], label='Approve'),
    # ...
])
```

**`core/mixins.py`** — import shared mixins from Keel, keep product-specific ones local:
```python
from keel.core.mixins import (  # noqa: F401
    AgencyObjectMixin,
    SortableListMixin,
    ZoneFormMixin,
)
# Product-specific mixins below...
```

**`core/sso.py`** — import the base adapter from Keel:
```python
from keel.core.sso import KeelSSOAdapter  # noqa: F401
# Product-specific adapter customizations below...
```

### Step 7: Add File Upload Validation

On any model or form that accepts file uploads, add Keel's validator:

```python
from keel.security.scanning import FileSecurityValidator

# In a model:
class Document(models.Model):
    file = models.FileField(upload_to='documents/', validators=[FileSecurityValidator()])

# Or in a form clean method:
def clean_file(self):
    f = self.cleaned_data['file']
    FileSecurityValidator()(f)
    return f
```

### Step 8: Copy Security Documentation

Copy these files to your product repo root:

```bash
cp /path/to/keel/docs/SECURITY.md ./SECURITY.md
cp /path/to/keel/docs/INCIDENT_RESPONSE.md ./docs/INCIDENT_RESPONSE.md
```

Update the product name and any product-specific details in the copied files.

### Step 9: Add CI/CD Security Scanning

**Option A** — Reference Keel's reusable workflow (recommended):
```yaml
# .github/workflows/ci.yml
jobs:
  security:
    uses: okeefedaniel/keel/.github/workflows/security.yml@main
    with:
      python-version: '3.12'
```

**Option B** — Copy the workflow file:
```bash
cp /path/to/keel/.github/workflows/security.yml ./.github/workflows/security.yml
```

Remove `continue-on-error: true` from any existing Bandit/Safety steps.

### Step 10: Add Security Event Monitoring

Add a cron job or Railway scheduled task to check for suspicious activity:

```bash
# Every 15 minutes
*/15 * * * * cd /app && python manage.py check_security_events
```

Or add to your `startup.py` / `Procfile`:
```
# Procfile
worker: while true; do python manage.py check_security_events; sleep 900; done
```

### Step 11: Verify Integration

Run the security audit to confirm everything is wired up:

```bash
python manage.py security_audit
```

All checks should pass. Fix any `FAIL` items before deploying.

For CI/CD, use the `--fail-on-error` flag to block deploys with security issues:
```bash
python manage.py security_audit --fail-on-error --json
```

---

## Quick Reference: Settings

| Setting | Default | Description |
|---------|---------|-------------|
| `KEEL_AUDIT_LOG_MODEL` | `'core.AuditLog'` | Dotted path to your AuditLog model |
| `KEEL_SECURITY_ALERT_RECIPIENTS` | `[]` | Email addresses for security alerts |
| `KEEL_SECURITY_ALERT_WEBHOOK` | `None` | Slack/Teams webhook URL |
| `KEEL_FILE_SCANNING_ENABLED` | `True` (prod) | Enable ClamAV file scanning |
| `KEEL_CLAMAV_SOCKET` | `/var/run/clamav/clamd.ctl` | ClamAV socket path or `tcp://host:port` |
| `KEEL_CLAMAV_FAIL_CLOSED` | `True` | Reject uploads if scanner unavailable |
| `KEEL_MAX_UPLOAD_SIZE` | `10MB` | Maximum file upload size |
| `KEEL_ALLOWED_UPLOAD_EXTENSIONS` | See above | Allowed file extensions |
| `KEEL_LOGIN_MAX_FAILURES` | `10` | Failed logins before lockout |
| `KEEL_LOGIN_LOCKOUT_WINDOW` | `900` | Window in seconds for failure counting |
| `KEEL_LOGIN_LOCKOUT_DURATION` | `1800` | Lockout duration in seconds |
| `KEEL_LOGIN_PATHS` | `['/auth/login/', ...]` | URL paths to monitor for failed logins |
| `KEEL_ADMIN_ALLOWED_IPS` | `[]` | IP addresses/CIDRs allowed to access /admin/ |
| `KEEL_BUSINESS_HOURS` | `(8, 18)` | Business hours tuple for after-hours alerts |
| `KEEL_PRODUCT_NAME` | `'DockLabs'` | Product name used in alert emails |
| `KEEL_CSP_POLICY` | `None` | Content-Security-Policy header value |
