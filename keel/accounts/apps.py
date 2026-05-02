from django.apps import AppConfig


class KeelAccountsConfig(AppConfig):
    name = 'keel.accounts'
    label = 'keel_accounts'
    verbose_name = 'Keel Accounts'
    default_auto_field = 'django.db.models.BigAutoField'

    def ready(self):
        # Register Organization and OrganizationProductSubscription for
        # automatic audit logging. Every create/update/delete on these
        # models emits an AuditLog row via post_save / post_delete
        # signals. Closes CSO finding S4 (subscription mutations not
        # audit-logged in plan).
        #
        # Auto-audit is wired only when the audit infrastructure is
        # available — products that use keel.accounts but not
        # keel.core (rare) won't import this and won't crash.
        try:
            from keel.core.audit_signals import register_audited_model
        except Exception:  # pragma: no cover — defensive
            return
        register_audited_model(
            'keel_accounts.Organization',
            'Organization',
        )
        register_audited_model(
            'keel_accounts.OrganizationProductSubscription',
            'Org Product Subscription',
        )
