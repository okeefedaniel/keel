"""AppConfig for keel.activity.

Wires post_save signals on the concrete AuditLog model (Track A promotion) and on the
concrete Activity model (notification fan-out dispatch). Calls into the central
``product_promotions.register_all_promotions()`` once apps are ready, which conditionally
registers per-product promotion rules for products that are in INSTALLED_APPS.

Standalone-deployability is preserved: a product deployed alone (Helm only, Beacon only,
etc.) skips registration of peers' promotion rules because their apps simply aren't
installed. ``apps.is_installed('helm.tasks')`` is the gate.
"""
from django.apps import AppConfig
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class ActivityConfig(AppConfig):
    name = 'keel.activity'
    label = 'keel_activity'
    verbose_name = 'Keel Activity'

    def ready(self):
        # Boot-time setting check: KEEL_ACTIVITY_MODEL must be set if keel.activity is installed.
        # Catches FK-resolution-at-migrate-time failures at boot instead of mid-migration.
        if not getattr(settings, 'KEEL_ACTIVITY_MODEL', None):
            raise ImproperlyConfigured(
                'keel.activity is in INSTALLED_APPS but KEEL_ACTIVITY_MODEL is not set in '
                'settings. Set it to the dotted path of your concrete Activity subclass, '
                'e.g. KEEL_ACTIVITY_MODEL = "tasks.Activity".'
            )
        if not getattr(settings, 'KEEL_WATCHER_MODEL', None):
            raise ImproperlyConfigured(
                'keel.activity is in INSTALLED_APPS but KEEL_WATCHER_MODEL is not set.'
            )
        if not getattr(settings, 'KEEL_PRODUCT_CODE', None):
            raise ImproperlyConfigured(
                'keel.activity is in INSTALLED_APPS but KEEL_PRODUCT_CODE is not set. '
                'Set it to a short identifier for this product, e.g. "helm", "manifest", "beacon".'
            )

        # Connect signals (post_save on AuditLog → promotion; post_save on Activity → dispatch).
        # Imported lazily so model resolution doesn't run at import time.
        from . import signals
        signals.connect_signals()

        # Register per-product promotion rules. Each _register_<product>_promotions() block
        # is wrapped in apps.is_installed() so a standalone deploy never registers peers' rules.
        from . import product_promotions
        product_promotions.register_all_promotions()

        # Auto-register VERB_CATALOG entries as NotificationTypes so they appear on
        # /notifications/preferences/ and per-user preference filtering takes effect on
        # the activity dispatch path. Keyed as 'activity.<verb.code>'. Idempotent —
        # skips any keys an upstream caller has already registered (so a product can
        # ship a richer NotificationType for a specific verb and the default skips it).
        from . import notifications as _activity_notifications
        _activity_notifications.register_verb_notification_types()
