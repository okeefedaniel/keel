"""Fiscal year and period management for DockLabs products.

Provides shared fiscal calendar infrastructure. CT fiscal year runs
July 1 through June 30. Periods are months within a fiscal year with
status tracking for close workflows.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from keel.core.models import KeelBaseModel


class FiscalYear(KeelBaseModel):
    """CT fiscal year: July 1 – June 30."""

    name = models.CharField(max_length=20)              # "FY2026"
    start_date = models.DateField()                     # 2025-07-01
    end_date = models.DateField()                       # 2026-06-30
    is_current = models.BooleanField(default=False)

    class Meta:
        ordering = ['-start_date']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Ensure only one fiscal year is marked as current
        if self.is_current:
            FiscalYear.objects.filter(is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)


class FiscalPeriod(KeelBaseModel):
    """A month within a fiscal year."""

    class Status(models.TextChoices):
        OPEN = 'open', _('Open')
        SUBMISSIONS_DUE = 'submissions_due', _('Submissions Due')
        UNDER_REVIEW = 'under_review', _('Under Review')
        CLOSED = 'closed', _('Closed')

    fiscal_year = models.ForeignKey(
        FiscalYear, on_delete=models.CASCADE, related_name='periods',
    )
    month = models.PositiveIntegerField()               # 1=July … 12=June
    label = models.CharField(max_length=20)             # "March 2026"
    start_date = models.DateField()
    end_date = models.DateField()
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.OPEN,
    )
    submission_deadline = models.DateTimeField(null=True, blank=True)
    close_deadline = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['fiscal_year', 'month']
        unique_together = ['fiscal_year', 'month']

    def __str__(self):
        return f"{self.label} ({self.fiscal_year.name})"
