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
    a NULL-user audit row, undoing the Approach D guarantee. The constraint
    is named ``auditlog_user_required`` so the canary gauge can verify it
    in information_schema.check_constraints on live deployments.
    """
    constraints = AbstractAuditLog._meta.constraints
    matching = [
        c for c in constraints
        if isinstance(c, CheckConstraint) and c.name == 'auditlog_user_required'
    ]
    assert matching, (
        'AbstractAuditLog.Meta.constraints must include a CheckConstraint '
        'named auditlog_user_required.'
    )


def test_concrete_keel_accounts_auditlog_carries_constraint():
    """The shipping concrete model must inherit / re-declare the constraint.

    Concrete subclasses don't auto-inherit Meta.constraints from an abstract
    base, so each AuditLog subclass needs to either re-declare or rely on
    a migration that re-adds the constraint. keel.accounts.AuditLog
    re-declares it in its own Meta — pin that to prevent drift.
    """
    from keel.accounts.models import AuditLog as KeelAuditLog
    names = {c.name for c in KeelAuditLog._meta.constraints
             if isinstance(c, CheckConstraint)}
    assert 'auditlog_user_required' in names, (
        'keel.accounts.AuditLog must declare the auditlog_user_required '
        'CheckConstraint on its own Meta — abstract constraints do not '
        'auto-propagate to concrete subclasses.'
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
