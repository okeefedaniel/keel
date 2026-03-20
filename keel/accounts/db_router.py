"""Database router for shared Keel accounts tables.

Routes all keel_accounts models to the 'keel' database, allowing
products to keep their domain data in their own database while
sharing a single user/auth store.

Usage in product settings.py:

    DATABASES = {
        'default': { ... },           # product's own database
        'keel': { ... },              # shared Keel database
    }

    DATABASE_ROUTERS = ['keel.accounts.db_router.KeelAccountsRouter']
"""

KEEL_APP_LABELS = {'keel_accounts', 'keel_requests', 'auth', 'contenttypes', 'sessions'}


class KeelAccountsRouter:
    """Route keel_accounts and auth models to the shared 'keel' database.

    If no 'keel' database is configured, all queries fall through to
    the default database (single-database deployments work unchanged).
    """

    def _is_keel_model(self, model):
        return model._meta.app_label in KEEL_APP_LABELS

    def db_for_read(self, model, **hints):
        if self._is_keel_model(model):
            return 'keel'
        return None

    def db_for_write(self, model, **hints):
        if self._is_keel_model(model):
            return 'keel'
        return None

    def allow_relation(self, obj1, obj2, **hints):
        """Allow relations between keel models and between keel ↔ product."""
        if self._is_keel_model(obj1) or self._is_keel_model(obj2):
            return True
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        """Keel models migrate to 'keel' db; product models to 'default'."""
        if app_label in KEEL_APP_LABELS:
            return db == 'keel'
        if db == 'keel':
            return False
        return None
