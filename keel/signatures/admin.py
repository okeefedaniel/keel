from django.contrib import admin

from .models import ManifestHandoff


@admin.register(ManifestHandoff)
class ManifestHandoffAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'source_model', 'source_pk', 'status',
        'manifest_packet_uuid', 'created_at', 'signed_at',
    )
    list_filter = ('status', 'source_app_label', 'source_model')
    search_fields = ('source_pk', 'manifest_packet_uuid', 'packet_label')
    readonly_fields = (
        'id', 'created_at', 'updated_at', 'signed_at',
        'source_app_label', 'source_model', 'source_pk',
        'manifest_packet_uuid', 'manifest_url', 'signed_pdf_url',
    )
