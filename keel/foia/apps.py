import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class KeelFOIAConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'keel.foia'
    label = 'keel_foia'
    verbose_name = 'Keel FOIA Compliance'


class FOIAReadyAppConfig(AppConfig):
    """Base AppConfig for products that must be FOIA-enabled.

    Subclass this in your product's AppConfig and implement
    ``register_foia_exports()`` to register exportable record types.

    Example:

        from keel.foia.apps import FOIAReadyAppConfig

        class LookoutConfig(FOIAReadyAppConfig):
            name = 'lookout'
            foia_product_name = 'lookout'

            def register_foia_exports(self):
                from keel.foia.export import foia_export_registry
                from .models import Testimony

                foia_export_registry.register(
                    product='lookout',
                    record_type='testimony',
                    queryset_fn=lambda: Testimony.objects.all(),
                    serializer_fn=self._serialize_testimony,
                    display_name='Testimony',
                    description='Legislative testimony documents',
                )

    On ``ready()``, this will:
    1. Call ``register_foia_exports()``
    2. Validate that at least one type was registered
    3. Warn if KEEL_FOIA_EXPORT_MODEL or KEEL_AUDIT_LOG_MODEL is not set
    """

    foia_product_name = ''  # Override with product name (e.g., 'lookout')

    def register_foia_exports(self):
        """Register exportable record types. Override in your product."""
        raise NotImplementedError(
            f'{self.__class__.__name__} must implement register_foia_exports()'
        )

    def ready(self):
        super().ready()
        self._validate_foia_settings()
        self.register_foia_exports()
        self._validate_registrations()

    def _validate_foia_settings(self):
        from django.conf import settings

        if not getattr(settings, 'KEEL_AUDIT_LOG_MODEL', None):
            logger.warning(
                'FOIA: %s — KEEL_AUDIT_LOG_MODEL is not set. '
                'Audit logging will use the default model path.',
                self.foia_product_name or self.name,
            )
        if not getattr(settings, 'KEEL_FOIA_EXPORT_MODEL', None):
            logger.warning(
                'FOIA: %s — KEEL_FOIA_EXPORT_MODEL is not set. '
                'FOIA record export to Admiralty will not work.',
                self.foia_product_name or self.name,
            )
        middleware = getattr(settings, 'MIDDLEWARE', [])
        if 'keel.core.middleware.AuditMiddleware' not in middleware:
            logger.warning(
                'FOIA: %s — AuditMiddleware is not in MIDDLEWARE. '
                'IP addresses will not be captured on requests.',
                self.foia_product_name or self.name,
            )

    def _validate_registrations(self):
        from .export import foia_export_registry

        product = self.foia_product_name or self.name
        types = foia_export_registry.get_exportable_types(product=product)
        if not types:
            logger.warning(
                'FOIA: %s has no registered exportable types. '
                'FOIA staff will not be able to export records from this product.',
                product,
            )
