"""Django admin registration for Keel accounts models."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import Agency, AuditLog, Invitation, KeelUser, ProductAccess


class ProductAccessInline(admin.TabularInline):
    model = ProductAccess
    fk_name = 'user'
    extra = 1
    fields = ('product', 'role', 'is_active', 'is_beta_tester', 'granted_at')
    readonly_fields = ('granted_at',)


@admin.register(KeelUser)
class KeelUserAdmin(UserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'agency', 'is_state_user', 'is_active')
    list_filter = ('is_state_user', 'is_active', 'is_staff', 'agency')
    search_fields = ('username', 'email', 'first_name', 'last_name')
    inlines = [ProductAccessInline]

    fieldsets = UserAdmin.fieldsets + (
        ('Keel Profile', {
            'fields': ('title', 'phone', 'agency', 'is_state_user', 'accepted_terms', 'accepted_terms_at'),
        }),
    )

    def has_add_permission(self, request):
        """Block the "+ Add user" button when running in suite mode.

        In suite mode all user creation must happen in the Keel admin.
        A user created in a product admin lives only in that product's
        DB, has no SocialAccount link to Keel, and can never SSO — which
        gives the illusion of working while silently stranding the user.
        See keel/core/utils.py is_suite_mode() for the detection rule.
        """
        from keel.core.utils import is_suite_mode
        if is_suite_mode():
            return False
        return super().has_add_permission(request)

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        """Surface a suite-mode warning banner on the user-edit form."""
        from keel.core.utils import is_suite_mode
        extra_context = extra_context or {}
        if is_suite_mode():
            extra_context['suite_mode_warning'] = (
                'This product is deployed in suite mode. Create and manage '
                'users at the Keel admin (https://keel.docklabs.ai/admin/) '
                "instead. Users created here will only exist in this "
                "product's database and will not be able to sign in via "
                'Keel OIDC.'
            )
        return super().changeform_view(request, object_id, form_url, extra_context)


@admin.register(Agency)
class AgencyAdmin(admin.ModelAdmin):
    list_display = ('abbreviation', 'name', 'is_active', 'contact_email')
    list_filter = ('is_active',)
    search_fields = ('name', 'abbreviation')


@admin.register(ProductAccess)
class ProductAccessAdmin(admin.ModelAdmin):
    list_display = ('user', 'product', 'role', 'is_active', 'is_beta_tester', 'granted_at')
    list_filter = ('product', 'role', 'is_active')
    search_fields = ('user__email', 'user__username')
    raw_id_fields = ('user', 'granted_by')


@admin.register(Invitation)
class InvitationAdmin(admin.ModelAdmin):
    list_display = ('email', 'product', 'role', 'status', 'invited_by', 'created_at', 'expires_at')
    list_filter = ('status', 'product')
    search_fields = ('email',)
    raw_id_fields = ('invited_by', 'accepted_by')
    readonly_fields = ('token',)


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'user', 'action', 'entity_type', 'product', 'ip_address')
    list_filter = ('action', 'product', 'entity_type')
    search_fields = ('description', 'user__email', 'user__username', 'entity_id')
    raw_id_fields = ('user',)
    readonly_fields = (
        'id', 'user', 'action', 'entity_type', 'entity_id',
        'description', 'changes', 'ip_address', 'product', 'timestamp',
    )
    date_hierarchy = 'timestamp'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
