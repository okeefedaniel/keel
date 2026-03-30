from django.contrib import admin

from .models import ReportSchema, ReportLineItem


class ReportLineItemInline(admin.TabularInline):
    model = ReportLineItem
    extra = 0
    fields = ('code', 'label', 'data_type', 'sort_order', 'is_required',
              'is_calculated', 'formula', 'group')
    ordering = ('sort_order',)


@admin.register(ReportSchema)
class ReportSchemaAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'product', 'version', 'is_active')
    list_filter = ('product', 'is_active')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}
    inlines = [ReportLineItemInline]


@admin.register(ReportLineItem)
class ReportLineItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'schema', 'data_type', 'sort_order',
                    'is_required', 'is_calculated')
    list_filter = ('schema', 'data_type', 'is_calculated')
    search_fields = ('code', 'label')
