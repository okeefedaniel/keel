"""Scheduling dashboard view.

Single page at ``/scheduling/`` listing every registered job in this
service with its last run, status, recent-runs sparkline, and an
admin-editable ``enabled`` toggle + ``notes`` field.

Restricted to is_staff or system_admin role — same gate as the Django
admin. Per-product services each have their own /scheduling/ showing
only that service's jobs.
"""
from datetime import timedelta

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from keel.scheduling.models import CommandRun, ScheduledJob
from keel.scheduling.registry import job_registry


@staff_member_required
def dashboard(request):
    """List every registered scheduled job with last run + status."""
    jobs = list(ScheduledJob.objects.all().prefetch_related('runs'))

    # Surface code-vs-DB drift: jobs declared in code but not synced,
    # and rows in DB but no longer declared.
    declared_slugs = {s.slug for s in job_registry.all()}
    db_slugs = {j.slug for j in jobs}
    pending_sync = declared_slugs - db_slugs
    orphaned = db_slugs - declared_slugs

    # Augment each job with computed fields the template needs.
    now = timezone.now()
    enriched = []
    for job in jobs:
        latest = job.latest_run()
        is_overdue = False
        if job.timeout_minutes and latest and latest.is_running:
            elapsed = (now - latest.started_at).total_seconds() / 60
            is_overdue = elapsed > job.timeout_minutes
        enriched.append({
            'job': job,
            'latest': latest,
            'recent': job.recent_runs(24),
            'success_rate': job.success_rate(),
            'is_overdue': is_overdue,
            'is_orphaned': job.slug in orphaned,
        })

    return render(request, 'keel/scheduling/dashboard.html', {
        'jobs': enriched,
        'pending_sync': sorted(pending_sync),
        'declared_count': len(declared_slugs),
        'db_count': len(db_slugs),
    })


@staff_member_required
@require_POST
def update_job(request, slug):
    """Update admin-editable fields (enabled, notes) on a single job."""
    job = get_object_or_404(ScheduledJob, slug=slug)
    enabled = request.POST.get('enabled') in ('on', 'true', '1', 'yes')
    notes = request.POST.get('notes', '').strip()
    fields = []
    if job.enabled != enabled:
        job.enabled = enabled
        fields.append('enabled')
    if job.notes != notes:
        job.notes = notes
        fields.append('notes')
    if fields:
        job.save(update_fields=fields + ['updated_at'])
        messages.success(request, f'Updated {", ".join(fields)} on {job.slug}.')
    return redirect('keel_scheduling:dashboard')


@staff_member_required
def job_detail(request, slug):
    """Per-job page with full run history (last 100) and error excerpts."""
    job = get_object_or_404(ScheduledJob, slug=slug)
    runs = list(job.runs.select_related('invoked_by').order_by('-started_at')[:100])
    return render(request, 'keel/scheduling/job_detail.html', {
        'job': job,
        'runs': runs,
        'success_rate': job.success_rate(),
    })
