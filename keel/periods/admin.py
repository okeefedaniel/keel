from django.contrib import admin

from .models import FiscalYear, FiscalPeriod


class FiscalPeriodInline(admin.TabularInline):
    model = FiscalPeriod
    extra = 0
    fields = ('month', 'label', 'start_date', 'end_date', 'status',
              'submission_deadline', 'close_deadline')
    ordering = ('month',)


@admin.register(FiscalYear)
class FiscalYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')
    list_filter = ('is_current',)
    inlines = [FiscalPeriodInline]


@admin.register(FiscalPeriod)
class FiscalPeriodAdmin(admin.ModelAdmin):
    list_display = ('label', 'fiscal_year', 'month', 'status',
                    'submission_deadline', 'close_deadline')
    list_filter = ('status', 'fiscal_year')
    search_fields = ('label',)
