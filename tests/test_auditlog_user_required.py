"""Schema constraint tests for ``AbstractAuditLog.user`` under Approach D.

v0.46.0 enforces ``AuditLog.user IS NOT NULL`` two ways:

1. ``null=False`` on the ForeignKey — Django ORM raises ``IntegrityError``
   at save time.
2. ``CheckConstraint(check=Q(user__isnull=False), name='auditlog_user_required')`` —
   DB-level guard so a raw INSERT can't sneak past the ORM either.

The constraint is also visible in ``information_schema.check_constraints``
on Postgres, which is how the canary's ``audit_constraint_present`` gauge
verifies the schema is in the expected state on a live deployment.
"""
from django.db.models import CheckConstraint, Q

from keel.core.models import AbstractAuditLog


def test_user_field_is_not_null_on_the_abstract():
    """``null=False`` on the abstract is the Django-level guard."""
    field = AbstractAuditLog._meta.get_field('user')
    assert field.null is False, (
        'AbstractAuditLog.user must be null=False under Approach D. System '
        'events route to Activity via record_system_event(), not AuditLog.'
    )
    assert field.blank is False


def test_user_field_on_delete_is_protect():
    """``on_delete=PROTECT`` — a user with audit history cannot be deleted.

    The legacy ``SET_NULL`` would have left orphan NULL-user rows, which the
    new CheckConstraint rejects. PROTECT is the only compatible choice.
    """
    from django.db.models import PROTECT
    field = AbstractAuditLog._meta.get_field('user')
    # field.remote_field.on_delete is the actual callable Django installs.
    assert field.remote_field.on_delete is PROTECT, (
        'AbstractAuditLog.user.on_delete must be PROTECT under Approach D '
        '(was SET_NULL pre-v0.46.0).'
    )


def test_auditlog_user_required_check_constraint_declared():
    """The defense-in-depth constraint must be declared on Meta.constraints.

    Without it, a raw SQL insert bypassing the Django ORM could still create
    a NULL-user audit row, undoing the Approach D guarantee. The name is
    TEMPLATED (``%(app_label)s_%(class)s_user_required``) so every concrete
    subclass gets a globally-unique constraint name and no two AuditLog
    subclasses collide under Django E032 (fixed in v0.48.1 — a hardcoded
    name made every consumer's makemigrations fail against keel.accounts.
    AuditLog's identically-named constraint).
    """
    constraints = AbstractAuditLog._meta.constraints
    matching = [
        c for c in constraints
        if isinstance(c, CheckConstraint)
        and c.name == '%(app_label)s_%(class)s_user_required'
    ]
    assert matching, (
        'AbstractAuditLog.Meta.constraints must include a CheckConstraint '
        'named %(app_label)s_%(class)s_user_required (templated so concrete '
        'subclasses get unique names — see v0.48.1 E032 fix).'
    )


def test_concrete_subclasses_get_distinct_constraint_names():
    """Two concrete AuditLog subclasses must NOT share a constraint name.

    This is the regression test for the v0.48.0 → v0.48.1 E032 bug: a
    hardcoded constraint name on the abstract meant the moment a consumer's
    concrete AuditLog inherited it AND keel.accounts.AuditLog also carried
    one, ``makemigrations`` failed project-wide. The templated name resolves
    per-subclass; keel.accounts.AuditLog keeps its own explicit name for
    migration-history stability. Either way, the two names differ.
    """
    from keel.accounts.models import AuditLog as KeelAuditLog
    keel_names = {
        c.name for c in KeelAuditLog._meta.constraints
        if isinstance(c, CheckConstraint) and 'user_required' in c.name
    }
    # keel.accounts.AuditLog declares its own name (kept stable across the
    # v0.48.1 fix so its already-applied migration 0022 needs no rename).
    assert keel_names, (
        'keel.accounts.AuditLog must carry a user_required CheckConstraint.'
    )
    # The abstract's templated name resolves to something app-specific for a
    # consumer subclass — it must NOT equal keel.accounts.AuditLog's name.
    abstract_template = next(
        c.name for c in AbstractAuditLog._meta.constraints
        if isinstance(c, CheckConstraint) and 'user_required' in c.name
    )
    assert abstract_template not in keel_names, (
        'Abstract constraint name must be templated so it cannot collide '
        'with keel.accounts.AuditLog (the E032 bug this fix closes).'
    )


def test_login_failed_and_security_event_removed_from_action_choices():
    """The two legacy security-event action choices migrated to Activity verbs.

    v0.46.0 removed them from the choices list (a CharField choice change,
    not a schema change — old rows with action='login_failed' still read,
    new rows cannot be written with those values via the ORM choice gate).
    """
    values = {c[0] for c in AbstractAuditLog.Action.choices}
    assert 'login_failed' not in values
    assert 'security_event' not in values
