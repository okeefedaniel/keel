from django.contrib import admin

from keel.scheduling.models import CommandRun, ScheduledJob


@admin.register(ScheduledJob)
class ScheduledJobAdmin(admin.ModelAdmin):
    list_display = (
        'slug', 'owner_product', 'name', 'cron_expression', 'enabled',
        'declared_at',
    )
    list_filter = ('owner_product', 'enabled')
    search_fields = ('slug', 'name', 'command', 'notes')
    readonly_fields = (
        'slug', 'name', 'command', 'cron_expression', 'owner_product',
        'description', 'timeout_minutes', 'declared_at', 'updated_at',
    )
    fieldsets = (
        ('Declaration (read-only — managed by @scheduled_job)', {
            'fields': (
                'slug', 'name', 'command', 'owner_product', 'cron_expression',
                'description', 'timeout_minutes', 'declared_at', 'updated_at',
            ),
        }),
        ('Admin-editable', {
            'fields': ('enabled', 'notes'),
        }),
    )


@admin.register(CommandRun)
class CommandRunAdmin(admin.ModelAdmin):
    list_display = (
        'job', 'started_at', 'finished_at', 'status', 'duration_ms',
    )
    list_filter = ('status', 'job')
    search_fields = ('job__slug', 'error_message')
    readonly_fields = (
        'job', 'started_at', 'finished_at', 'status', 'duration_ms',
        'error_message', 'invoked_by',
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
