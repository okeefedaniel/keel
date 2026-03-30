"""Schema-based structured data collection for DockLabs products.

Define a set of typed line items (currency, integer, text), collect
values against them, and validate. Reusable across products and
program types.

Purser uses this for monthly close report schemas. Harbor could adopt
it for SF-425 federal financial reports and structured reporting.
"""
from django.db import models
from django.utils.translation import gettext_lazy as _

from keel.core.models import KeelBaseModel


class ReportSchema(KeelBaseModel):
    """Defines a set of line items for a type of report.

    Reusable across products and program types. Each schema belongs
    to a product (e.g., 'purser', 'harbor') and can have multiple
    versions.
    """

    name = models.CharField(max_length=200)             # "Grant Program Monthly Close"
    slug = models.SlugField(unique=True)                # "grant-monthly-close"
    description = models.TextField(blank=True)
    product = models.CharField(max_length=50)           # "purser"
    version = models.PositiveIntegerField(default=1)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['product', 'name']

    def __str__(self):
        return f"{self.name} (v{self.version})"


class ReportLineItem(KeelBaseModel):
    """A single field in a report schema."""

    class DataType(models.TextChoices):
        CURRENCY = 'currency', _('Currency')
        INTEGER = 'integer', _('Integer')
        DECIMAL = 'decimal', _('Decimal')
        TEXT = 'text', _('Text')
        BOOLEAN = 'boolean', _('Yes/No')

    schema = models.ForeignKey(
        ReportSchema, on_delete=models.CASCADE, related_name='line_items',
    )
    code = models.CharField(max_length=20)              # "DISB"
    label = models.CharField(max_length=200)            # "Disbursements"
    description = models.TextField(blank=True)          # Help text for submitters
    data_type = models.CharField(
        max_length=20, choices=DataType.choices, default=DataType.CURRENCY,
    )
    sort_order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)
    is_calculated = models.BooleanField(default=False)
    formula = models.TextField(blank=True)              # "BEG_BAL + OBLIG - DISB - DEOBLIG"
    group = models.CharField(max_length=100, blank=True)  # Visual grouping header

    class Meta:
        ordering = ['schema', 'sort_order']
        unique_together = ['schema', 'code']

    def __str__(self):
        return f"{self.code}: {self.label}"
