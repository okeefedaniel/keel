from django.contrib import admin

from .models import Municipality, MunicipalityAlias


class MunicipalityAliasInline(admin.TabularInline):
    model = MunicipalityAlias
    extra = 0
    fields = ('alias', 'multi_town', 'source')
    readonly_fields = ('source',)


@admin.register(Municipality)
class MunicipalityAdmin(admin.ModelAdmin):
    list_display = ('number', 'name', 'county', 'council_of_governments', 'population')
    list_filter = ('county', 'cog_abbr')
    search_fields = ('name', 'aliases__alias')
    ordering = ('number',)
    inlines = [MunicipalityAliasInline]

    def get_readonly_fields(self, request, obj=None):
        # number and slug cross product boundaries and public URLs; an edit
        # here would diverge from every other product's copy of the table.
        return ('number', 'slug') if obj else ()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MunicipalityAlias)
class MunicipalityAliasAdmin(admin.ModelAdmin):
    list_display = ('alias', 'municipality', 'multi_town', 'source', 'created_at')
    list_filter = ('source', 'multi_town')
    search_fields = ('alias', 'municipality__name')
    autocomplete_fields = ('municipality',)
    readonly_fields = ('source', 'created_at')

    def save_model(self, request, obj, form, change):
        # Anything saved through the admin belongs to the operator from then
        # on: load_ct_municipalities never overwrites or deletes an admin row.
        obj.source = MunicipalityAlias.Source.ADMIN
        super().save_model(request, obj, form, change)
