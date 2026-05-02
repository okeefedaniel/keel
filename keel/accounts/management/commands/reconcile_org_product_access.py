"""Daily reconciliation of ProductAccess against org subscriptions.

Defense-in-depth for cases where ``KeelUser.save``'s org-change hook is
bypassed (raw SQL fixes, replication-based bulk imports, multi-step
admin scripts that update users without going through the full ORM).
The save hook covers the normal admin-edit path; this command catches
everything else.

Registered with ``keel.scheduling`` so its run history shows up on the
``/scheduling/`` dashboard. The cron itself is owned by Railway / GHA
/ external scheduler — keel does not invoke commands itself.
"""
from django.core.management.base import BaseCommand

from keel.accounts.services import reconcile_all_users
from keel.scheduling import scheduled_job


@scheduled_job(
    slug='keel-reconcile-org-product-access',
    name='Keel — Daily ProductAccess vs Subscription reconcile',
    cron='0 4 * * *',
    owner='keel',
    notes=(
        'Sweeps every non-superuser KeelUser, deactivating ProductAccess '
        'rows whose product is not in the user\'s organization\'s active '
        'subscription set. Idempotent: safe to re-run any time. Closes '
        'CSO finding S1 (privilege bleed on org reassignment) for cases '
        'where the KeelUser.save() hook is bypassed.'
    ),
)
class Command(BaseCommand):
    help = (
        'Daily reconcile: deactivate ProductAccess rows for products '
        'the user\'s org no longer subscribes to.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--force-logout',
            action='store_true',
            help=(
                'Bump last_logout_at on every user with a deactivation '
                '(forces re-login via SessionFreshnessMiddleware). Off '
                'by default for the cron path so a sweep doesn\'t kick '
                'every user out nightly.'
            ),
        )

    def handle(self, *args, **opts):
        force_logout = opts.get('force_logout', False)
        report = reconcile_all_users(force_logout=force_logout)
        self.stdout.write(self.style.SUCCESS(
            f"Reconcile complete: scanned {report['users_scanned']} users, "
            f"revoked {report['rows_revoked']} ProductAccess rows "
            f"(force_logout={force_logout})."
        ))
