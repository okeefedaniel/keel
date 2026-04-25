"""Suite-wide scheduling registry + run log + admin dashboard.

The scheduler itself is external (Railway cron services, GitHub Actions
schedules, cron-job.org, whatever the deployment uses). This module
provides three things on top of the existing pattern of
``BaseCommand`` + external cron:

1. **Registry** — products declare their scheduled commands via the
   ``@scheduled_job`` decorator. The decorator adds metadata to the
   command class and registers a spec in a module-level dict.

2. **Run log** — the decorator wraps ``BaseCommand.handle()`` so every
   invocation creates a ``CommandRun`` row capturing started_at /
   finished_at / status / error / duration. Cron failures become
   visible in the database, not just buried in Railway logs.

3. **Dashboard** — a single page at ``/scheduling/`` lists every
   registered job with its last run, status, recent run history, plus
   admin-editable ``enabled`` and ``notes`` fields.

Schedule expressions are display-only; the cron itself runs externally.
"""
default_app_config = 'keel.scheduling.apps.SchedulingConfig'

from keel.scheduling.decorators import scheduled_job  # noqa: E402,F401
from keel.scheduling.registry import job_registry  # noqa: E402,F401
