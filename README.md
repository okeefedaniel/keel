# Keel — DockLabs Shared Platform

Shared Django infrastructure for DockLabs products (Beacon, Harbor, Manifest).

## Install

```bash
pip install git+https://github.com/okeefedaniel/keel.git
```

## What's included

### keel.core
- **AbstractUser, AbstractAgency, AbstractAuditLog, AbstractNotification, AbstractArchivedRecord** — Abstract base models
- **WorkflowEngine** — Declarative status-transition system with role guards
- **AuditMiddleware** — Request IP extraction + login audit logging
- **ZoneFormMixin** — FOIA zone-aware form field filtering
- **SortableListMixin, AgencyObjectMixin** — Reusable view mixins
- **safe_redirect_url, rate_limit** — Security utilities
- **KeelSSOAdapter** — Configurable Microsoft Entra ID SSO adapter

### keel.foia
- **Abstract FOIA models** — FOIARequest, FOIAScope, FOIASearchResult, FOIADetermination, FOIAResponsePackage, FOIAAppeal
- **FOIA search engine** — Zone-aware record search across models
- **FOIA workflow** — Status transitions for request lifecycle
- **AI review** — Claude-powered pre-classification of search results

## Usage

Add to INSTALLED_APPS:
```python
INSTALLED_APPS = [
    'keel.core',
    # 'keel.foia',  # optional
    ...
]
```

Extend the abstract models in your app:
```python
from keel.core.models import AbstractAuditLog

class AuditLog(AbstractAuditLog):
    class Meta(AbstractAuditLog.Meta):
        pass
```
