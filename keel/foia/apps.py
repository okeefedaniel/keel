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
    On ``ready()`` it registers those types, then validates that the
    product is wired for FOIA (settings + at least one exportable type),
    emitting warnings — never hard failures — so a misconfigured product
    still boots but surfaces the gap in the logs and via ``foia_audit``.

    Example::

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

    Validation is intentionally non-fatal (logger.warning, not raise) so a
    deploy never crash-loops on a FOIA-config gap. Run ``python manage.py
    foia_audit --fail-on-error`` in CI to turn the same gaps into a hard gate.
    """

    #: Override with the product code (e.g. 'lookout'). Falls back to ``name``.
    foia_product_name = ''

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

    @property
    def _product(self):
        return self.foia_product_name or self.name

    def _validate_foia_settings(self):
        from django.conf import settings

        if not getattr(settings, 'KEEL_AUDIT_LOG_MODEL', None):
            logger.warning(
                'FOIA: %s — KEEL_AUDIT_LOG_MODEL is not set. '
                'Audit logging will use the default model path.',
                self._product,
            )
        if not getattr(settings, 'KEEL_FOIA_EXPORT_MODEL', None):
            logger.warning(
                'FOIA: %s — KEEL_FOIA_EXPORT_MODEL is not set. '
                'FOIA record export to Admiralty will not work.',
                self._product,
            )
        if 'keel.core.middleware.AuditMiddleware' not in getattr(settings, 'MIDDLEWARE', []):
            logger.warning(
                'FOIA: %s — AuditMiddleware is not in MIDDLEWARE. '
                'IP addresses will not be captured on requests.',
                self._product,
            )

    def _validate_registrations(self):
        from .export import foia_export_registry

        if not foia_export_registry.get_exportable_types(product=self._product):
            logger.warning(
                'FOIA: %s has no registered exportable types. '
                'FOIA staff will not be able to export records from this product.',
                self._product,
            )
