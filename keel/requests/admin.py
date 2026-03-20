"""Django admin registration for change request models."""
from django.contrib import admin

from .models import ChangeRequest


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ('title', 'product', 'category', 'priority', 'status', 'submitted_by_name', 'created_at')
    list_filter = ('status', 'product', 'category', 'priority')
    search_fields = ('title', 'description', 'submitted_by_name', 'submitted_by_email')
    readonly_fields = ('id', 'submitted_by', 'submitted_by_name', 'submitted_by_email', 'created_at', 'updated_at')
    raw_id_fields = ('reviewed_by',)
