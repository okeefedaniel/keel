from django.contrib import admin

from .models import ComplianceTemplate, ComplianceObligation, ComplianceItem


class ComplianceItemInline(admin.TabularInline):
    model = ComplianceItem
    extra = 0
    fields = ('label', 'due_date', 'status', 'submitted_at', 'reviewed_at')
    readonly_fields = ('submitted_at', 'reviewed_at')
    ordering = ('due_date',)


@admin.register(ComplianceTemplate)
class ComplianceTemplateAdmin(admin.ModelAdmin):
    list_display = ('name', 'requirement_type', 'cadence',
                    'reminder_lead_days', 'escalation_after_days')
    list_filter = ('requirement_type', 'cadence')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(ComplianceObligation)
class ComplianceObligationAdmin(admin.ModelAdmin):
    list_display = ('template', 'contract_number', 'start_date',
                    'end_date', 'is_active')
    list_filter = ('is_active', 'template')
    search_fields = ('contract_number',)
    inlines = [ComplianceItemInline]


@admin.register(ComplianceItem)
class ComplianceItemAdmin(admin.ModelAdmin):
    list_display = ('label', 'obligation', 'due_date', 'status',
                    'submitted_at', 'reviewed_at')
    list_filter = ('status',)
    search_fields = ('label',)
    raw_id_fields = ('submitted_by', 'reviewed_by')
