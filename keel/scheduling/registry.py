"""Module-level registry of declared ``ScheduledJob`` specs.

The decorator (``keel.scheduling.decorators.scheduled_job``) populates this
at import time. The ``sync_scheduled_jobs`` management command upserts
the registry contents into the DB so the dashboard can display them.

Why a Python registry alongside the DB:
- The DB row is admin-editable (``enabled``, ``notes``) and survives across
  deploys. Admins toggle it without code changes.
- The Python registry is the source-of-truth for which commands ARE
  schedulable — code-as-config. ``sync_scheduled_jobs`` keeps the DB in
  step. Removing the decorator from a command will leave the DB row
  orphaned (visible in the dashboard with a warning) until manually
  cleaned up.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ScheduledJobSpec:
    """A declared scheduled job — produced by the @scheduled_job decorator.

    All fields are display-only metadata. The actual schedule is
    configured externally (Railway cron service, GitHub Actions cron,
    cron-job.org, etc.) — keel does not invoke commands itself.
    """

    slug: str                    # Unique identifier, e.g. 'helm-notify-due-tasks'
    name: str                    # Human-readable display name
    command: str                 # Django management command name
    cron_expression: str         # Display-only schedule, e.g. '0 9 * * *'
    owner_product: str           # 'helm', 'admiralty', etc.
    notes: str = ''              # Default notes; admin can override per-row
    description: str = ''        # Longer description
    timeout_minutes: Optional[int] = None  # Display only — alerts after this


_registry: dict[str, ScheduledJobSpec] = {}


def register(spec: ScheduledJobSpec) -> None:
    """Register a job spec. Idempotent — re-registration overwrites.

    Called by the @scheduled_job decorator at import time. Tests may also
    register specs directly.
    """
    _registry[spec.slug] = spec


def get(slug: str) -> Optional[ScheduledJobSpec]:
    return _registry.get(slug)


def all_specs() -> list[ScheduledJobSpec]:
    return sorted(_registry.values(), key=lambda s: (s.owner_product, s.slug))


def clear() -> None:
    """Test-only helper to reset the registry."""
    _registry.clear()


# Public alias for clarity at import sites.
job_registry = type('JobRegistry', (), {
    'register': staticmethod(register),
    'get': staticmethod(get),
    'all': staticmethod(all_specs),
    'clear': staticmethod(clear),
})()
