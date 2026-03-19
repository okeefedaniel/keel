"""
Keel FOIA Module — Extractable FOIA compliance workflow.

This module can be used standalone or integrated with Beacon CRM.
It provides:
- FOIA request intake and tracking
- Search scope definition
- Record search across data zones
- AI-powered classification review
- Attorney determination workflow
- Response package compilation
- Appeal tracking
- Statutory exemption management

Standalone usage:
    INSTALLED_APPS = [
        ...
        'keel.foia',
    ]

Integrated usage (in Beacon):
    The Beacon CRM includes this as part of its FOIA workflow,
    with zone-aware search across interactions and notes.
"""
