from django.apps import AppConfig


class OpsConfig(AppConfig):
    """App config for the Keel /ops/ cross-product operational console.

    The module is mounted as a Django app so its templates dir is on the
    APP_DIRS template loader path. Has no models — just views, aggregator,
    and templates.
    """
    name = 'keel_site.ops'
    label = 'keel_site_ops'
    verbose_name = 'Keel Ops Console'
