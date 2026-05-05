"""Abstract models for keel.activity.

Activity is per-product: each product subclasses ``AbstractActivity`` and adds its own
denormalized FK (e.g. ``project = FK(Project)`` in helm.tasks) to make detail-page queries
fast. Watchers are per-product for the same reason: a user's watch on a Helm project is
local to Helm. Cross-product watchers are deferred to Phase 2.

Visibility tiers (5):
    - ``collaborators`` (default): visible to active collaborators on the target record.
    - ``agency``: visible to anyone in ``Organization.agency`` (per keel ≥ 0.22).
    - ``staff``: internal staff only (Django ``is_staff``).
    - ``public``: visible to anyone with read access on the target.
    - ``stub``: render actor + verb + date only, NO target details. For Beacon's zone-bridge
      use case where activity occurred in a more-restricted zone but readers in less-restricted
      zones should know "something happened" without seeing what.

Concrete subclasses MUST implement two visibility methods:
    - ``visible_to(user, queryset=None)`` returns a filtered queryset (used by feed render).
    - ``is_visible_to_user(user, activity)`` returns bool (used by dispatch fan-out).
"""
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models import Q, UniqueConstraint


VISIBILITY_CHOICES = [
    ('collaborators', 'Collaborators'),
    ('agency', 'Agency-wide'),
    ('staff', 'Internal staff only'),
    ('public', 'Public on this record'),
    ('stub', 'Cross-zone stub (actor + verb + date only)'),
]


class AbstractActivity(models.Model):
    """User-visible projection of an audit event.

    ┌─────────────────────────────────────────────────────────────────┐
    │ Audit (immutable, system-level)                                 │
    │   ↓ promote (declarative registry, Track A)                     │
    │ Activity (visibility-scoped, deep-linkable, this model)         │
    │   ↓ notify (Watcher + Collaborator + recipient_resolver)        │
    │ Notification (per-user, per-channel)                            │
    └─────────────────────────────────────────────────────────────────┘

    Activities are written either by the auto-promotion signal (Track A: post_save on
    AuditLog → registry lookup → Activity.create) or by explicit ``record_activity()``
    calls in service code (Track B: domain-rich verbs that need structured metadata
    that the audit-row snapshot can't capture, e.g. status transitions, signing events).

    Subclasses extend with a denormalized owning-entity FK for query speed:

        class Activity(AbstractActivity):
            project = models.ForeignKey(Project, on_delete=CASCADE, related_name='activities')

            @classmethod
            def visible_to(cls, user, queryset=None):
                ...

            @classmethod
            def is_visible_to_user(cls, user, activity):
                ...
    """

    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
        help_text='User who performed the action. Null for system events.',
    )
    verb = models.CharField(
        max_length=64, db_index=True,
        help_text='Dotted snake_case identifier from the verb catalog '
                  '(e.g. "collab.added", "signing.signed", "interaction.logged").',
    )

    # Primary target of the activity (the record the activity is "about").
    # GFK so any model can be a target. Both fields are nullable for system events
    # that don't tie to a specific record (e.g. "aggregator imported 47 records").
    target_ct = models.ForeignKey(
        ContentType, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    # CharField instead of PositiveIntegerField so the GFK can target UUID-PK
    # models (Beacon's Company/Contact/Interaction, Manifest's SigningPacket).
    # Django's GenericForeignKey stringifies any PK type into the object_id
    # field; CharField holds both stringified ints and UUID strings cleanly.
    # PositiveIntegerField would overflow on UUIDs (their .int is 128-bit;
    # SQLite INTEGER is 64-bit). Verified failure mode:
    # OverflowError: Python int too large to convert to SQLite INTEGER.
    target_id = models.CharField(max_length=64, null=True, blank=True)
    target = GenericForeignKey('target_ct', 'target_id')

    # Secondary object the activity acted on (e.g. for "collab.added", target=Project,
    # action=Collaborator row). Optional; many verbs don't need it.
    action_ct = models.ForeignKey(
        ContentType, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='+',
    )
    action_id = models.CharField(max_length=64, null=True, blank=True)
    action = GenericForeignKey('action_ct', 'action_id')

    visibility = models.CharField(
        max_length=16, choices=VISIBILITY_CHOICES,
        default='collaborators', db_index=True,
    )

    source_product = models.CharField(
        max_length=32, db_index=True,
        help_text='Short identifier for the product that emitted this row (helm, manifest, '
                  'beacon, etc). Comes from settings.KEEL_PRODUCT_CODE.',
    )
    deep_link = models.URLField(
        max_length=512, blank=True, default='',
        help_text='Absolute URL of the target, frozen at write time. Used for cross-product '
                  'navigation in Helm aggregator. Computed from target.get_absolute_url() '
                  'prefixed with KEEL_PRODUCT_BASE_URL at write time.',
    )
    source_label = models.CharField(
        max_length=255, blank=True, default='',
        help_text='Human-readable summary, e.g. "added Alice as Lead". Renders in feed UI.',
    )

    audit_ref = models.ForeignKey(
        settings.KEEL_AUDIT_LOG_MODEL,
        null=True, blank=True,
        on_delete=models.PROTECT,
        related_name='+',
        help_text='Back-pointer to the AuditLog row that triggered (Track A) or accompanied '
                  '(Track B) this activity. PROTECT because deleting an audit row would orphan '
                  'the activity. Track-A duplicate prevention uses the unique constraint below.',
    )
    metadata = models.JSONField(
        default=dict, blank=True,
        help_text='Free-form context: from/to status for transitions, signer email for sign '
                  'events, role for collaborator changes, zone for Beacon interactions, etc. '
                  'Distinct from audit.changes which carries the snapshot of audited fields.',
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        abstract = True
        constraints = [
            # Track A creates one Activity per audit row; this constraint prevents a buggy
            # promotion handler from double-creating on signal re-entry.
            UniqueConstraint(
                fields=['audit_ref'],
                condition=Q(audit_ref__isnull=False),
                name='%(app_label)s_%(class)s_unique_audit_ref',
            ),
        ]
        indexes = [
            # Per-target chronological feed (project detail page, contact detail, packet detail).
            models.Index(
                fields=['target_ct', 'target_id', '-created_at'],
                name='%(app_label)s_%(class)s_target_idx',
            ),
            # Per-actor feed ("activity by Alice").
            models.Index(
                fields=['actor', '-created_at'],
                name='%(app_label)s_%(class)s_actor_idx',
            ),
            # Per-verb filtering (Helm aggregator with verb filter, watcher matching).
            models.Index(
                fields=['verb', '-created_at'],
                name='%(app_label)s_%(class)s_verb_idx',
            ),
        ]
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.actor or "system"} {self.verb} {self.target}'

    @classmethod
    def visible_to(cls, user, queryset=None):
        """Returns the subset of activities the user has visibility on, as a queryset.

        Used for feed rendering on detail pages. MUST be implemented per product.

        The base implementation returns staff/superuser → all rows; everything else raises
        NotImplementedError to fail-loud rather than silently returning everything or nothing.
        """
        qs = queryset if queryset is not None else cls.objects.all()
        if user is None:
            # Defensive: never trust None. Empty queryset is the safe default.
            return qs.none()
        if user.is_staff or user.is_superuser:
            return qs
        raise NotImplementedError(
            f'{cls.__name__}.visible_to(user) must be implemented per product. '
            f'See helm.tasks.Activity for the reference implementation.'
        )

    @classmethod
    def is_visible_to_user(cls, user, activity) -> bool:
        """Per-subscriber visibility check used by dispatch fan-out.

        Same predicate as visible_to but evaluates a single row. Splitting the API means
        feed render uses SQL-side filtering (visible_to) and dispatch uses Python-side
        per-subscriber checks (is_visible_to_user) — they answer different questions.

        Stub-tier rows ALWAYS go through this check before any notification fires; that's
        how Beacon's cross-zone leak protection works. The base implementation here returns
        False for stub rows when the caller hasn't subclassed; that's fail-safe.
        """
        if user is None:
            return False
        if user.is_staff or user.is_superuser:
            return True
        # Subclasses MUST override this. The default below would silently hide all activity
        # from non-staff users, which would mask a missing implementation.
        raise NotImplementedError(
            f'{cls.__name__}.is_visible_to_user(user, activity) must be implemented per product.'
        )

    def render_for(self, user):
        """Returns a dict suitable for template rendering.

        Stub-tier rows hide target/deep_link/source_label and render only actor + verb + date.
        This is the cross-zone protection for Beacon's `interaction.logged` activity rows
        whose originating zone is more restricted than the viewer's zone.
        """
        if self.visibility == 'stub':
            return {
                'actor_name': str(self.actor) if self.actor else 'system',
                'verb': self.verb,
                'created_at': self.created_at,
                'is_stub': True,
            }
        return {
            'actor_name': str(self.actor) if self.actor else 'system',
            'verb': self.verb,
            'target': self.target,
            'deep_link': self.deep_link,
            'source_label': self.source_label,
            'created_at': self.created_at,
            'metadata': self.metadata,
            'is_stub': False,
        }


class AbstractWatcher(models.Model):
    """Generalizes Beacon's existing ``Follow(user, company OR contact)`` model.

    A watcher subscribes a user to notifications for activity rows matching specific
    target/verb/predicate criteria. Beacon's existing Follow rows migrate cleanly into
    this shape during Phase 1A Week 4: each Follow row becomes one Watcher row with
    target_ct pointing at Company or Contact and target_id set.

    Phase 1A scope:
        - Per-record watch: target_ct + target_id set.
        - Cross-target watch by type: target_ct set, target_id null (e.g. "all companies").
        - Verb whitelist: only fire for activities whose verb is in notify_verbs (empty list
          = all visible verbs).

    Phase 2 scope (deferred):
        - Cross-product watchers (filter_predicate path-portability across products).
        - Operator support on filter_predicate (gt/lt/contains/in).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='+',
    )
    target_ct = models.ForeignKey(
        ContentType, null=True, blank=True,
        on_delete=models.CASCADE, related_name='+',
        help_text='Null = match any content type (rare; usually only for staff watchers).',
    )
    # CharField for UUID-PK compatibility (see AbstractActivity.target_id comment).
    target_id = models.CharField(
        max_length=64, null=True, blank=True,
        help_text='Null with target_ct set = "all records of this type". '
                  'Both null = global watcher (rare).',
    )
    filter_predicate = models.JSONField(
        null=True, blank=True,
        help_text='Dotted-path keys against activity.metadata or target fields. Exact-equal '
                  'values only in v1 (no operators). Example: '
                  '{"metadata.from_status": "draft", "target.agency.abbr": "DEC"}.',
    )
    notify_verbs = models.JSONField(
        default=list, blank=True,
        help_text='List of verb strings. Empty = match all visible verbs.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        constraints = [
            UniqueConstraint(
                fields=['user', 'target_ct', 'target_id'],
                condition=Q(target_ct__isnull=False) & Q(target_id__isnull=False),
                name='%(app_label)s_%(class)s_unique_user_target',
            ),
        ]
        indexes = [
            models.Index(
                fields=['user', 'target_ct', 'target_id'],
                name='%(app_label)s_%(class)s_user_target_idx',
            ),
        ]

    def matches(self, activity) -> bool:
        """Returns True if this watcher should be considered for the given activity row.

        Stub-tier visibility check is NOT done here — that's enforced in dispatch via
        ``Activity.is_visible_to_user(user, activity)``. Beacon's zone-isolation guarantee
        depends on the dispatch-side check, not here.
        """
        if self.target_ct_id and self.target_ct_id != activity.target_ct_id:
            return False
        if self.target_id and self.target_id != activity.target_id:
            return False
        if self.notify_verbs and activity.verb not in self.notify_verbs:
            return False
        if self.filter_predicate:
            return _evaluate_predicate(self.filter_predicate, activity)
        return True


def _evaluate_predicate(predicate: dict, activity) -> bool:
    """Evaluate a Watcher.filter_predicate dict against an activity row.

    Keys are dotted paths: "metadata.foo" reads activity.metadata['foo'];
    "target.agency.abbr" reads activity.target.agency.abbr.

    Values are exact-equal matches only in v1. Any path that fails to resolve (KeyError,
    AttributeError, None hop) is treated as a non-match.
    """
    for path, expected in predicate.items():
        actual = _resolve_path(activity, path)
        if actual != expected:
            return False
    return True


def _resolve_path(obj, dotted_path: str):
    """Resolve a dotted path against an object. Returns None on any failure."""
    parts = dotted_path.split('.')
    current = obj
    for part in parts:
        if current is None:
            return None
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)
    return current
