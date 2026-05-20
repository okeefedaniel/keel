"""Source-scoped system-event verbs (Approach D, v0.46.0).

The verb catalog gained a dozen ``<source>.<verb>`` entries for the
canonical cron-summary events plus the four ``auth.*`` / ``security.*``
verbs that replace the legacy AuditLog action choices. Verbs are advisory
(CharField) but the catalog pins the names so they don't drift
product-to-product.
"""

REQUIRED_SYSTEM_VERBS = [
    'grants_gov.polled',
    'salesforce.synced',
    'openstates.polled',
    'foia.cache_refreshed',
    'invitations.pulled',
    'webhook.retried',
    'health.computed',
    'tasks.notified',
]

REQUIRED_AUTH_VERBS = [
    'auth.login_failed',
    'auth.login_succeeded',
    'security.account_locked',
    'security.suspicious_activity',
]


def test_all_source_scoped_verbs_registered():
    from keel.activity.verbs import VERB_CATALOG
    for code in REQUIRED_SYSTEM_VERBS + REQUIRED_AUTH_VERBS:
        assert code in VERB_CATALOG, (
            f'Verb {code!r} must be registered in VERB_CATALOG. '
            f'Approach D (v0.46.0) pins these as the canonical names.'
        )


def test_verb_descriptions_populated_for_new_verbs():
    """The VERB_DESCRIPTIONS index drives /ops/ tooltip rendering — every
    new system / auth verb should have a description."""
    from keel.activity.verbs import VERB_DESCRIPTIONS
    for code in REQUIRED_SYSTEM_VERBS + REQUIRED_AUTH_VERBS:
        assert code in VERB_DESCRIPTIONS, (
            f'Verb {code!r} must have a non-empty description.'
        )


def test_system_event_verbs_default_to_staff_visibility_no_notify():
    """System events are operational, not collaborator-facing. The default
    visibility should be 'staff' and default_notify=False so routine OK
    events don't push to inboxes."""
    from keel.activity.verbs import VERB_CATALOG
    for code in REQUIRED_SYSTEM_VERBS:
        verb = VERB_CATALOG[code]
        assert verb.default_visibility == 'staff', (
            f'{code} default_visibility must be staff (operational only).'
        )
        assert verb.default_notify is False, (
            f'{code} default_notify must be False (pull-only by default).'
        )
