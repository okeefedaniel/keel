"""Seed ai_enabled=True on existing active subscriptions.

Rationale (from /plan-eng-review finding 1E):

The schema migration in 0018 added ``ai_enabled = BooleanField(default=False)``
to ``OrganizationProductSubscription``. Without a backfill, every existing
customer's AI surfaces vanish on the deploy of keel 0.29.0 — analysts who
were using Beacon's news lookup yesterday get blank cards today, with no
warning and no path to fix without an admin in Keel.

Default-False is the correct security posture for *future* subs (no surprise
billing on new customers). For *existing* active subs, the customer was
already using AI through the legacy deployment-wide ``ANTHROPIC_API_KEY``
fallback. Flipping ``ai_enabled=True`` keeps their surfaces visible. The
per-user ``ProductAccess.ai_enabled`` (default True) and the user-key gate
together still ensure only users who set their own Anthropic key get to
make Claude calls — so this backfill doesn't open a billing hole.

Net effect: existing analysts see AI surfaces with the inline "you have not
yet put in your API key" prompt instead of an unexplained empty card. New
customers (no existing sub yet) hit the default-False gate as designed.

Reverse migration is a noop: we don't want to flip back to False on
``manage.py migrate keel_accounts 0019``. If a deployer truly wants to
default-deny existing subs, they can do it via Django admin — there's no
clean "undo" semantics here.
"""

from django.db import migrations


def seed_ai_enabled_on_active_subs(apps, schema_editor):
    OrgSub = apps.get_model('keel_accounts', 'OrganizationProductSubscription')
    OrgSub.objects.filter(is_active=True).update(ai_enabled=True)


class Migration(migrations.Migration):

    dependencies = [
        ('keel_accounts', '0019_alter_auditlog_action'),
    ]

    operations = [
        migrations.RunPython(
            seed_ai_enabled_on_active_subs,
            migrations.RunPython.noop,
        ),
    ]
