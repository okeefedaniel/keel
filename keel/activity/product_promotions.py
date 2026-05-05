"""Central per-product promotion-rule registration.

Mirrors the ``keel/notifications/product_types.py`` pattern. Each product gets a
``_register_<product>_promotions()`` function that registers Track A promotion rules.
``register_all_promotions()`` calls only those functions whose product's app is
installed — standalone deploys don't register peers' rules.

**Track A vs Track B reminder** (see ``MIGRATION-NOTES.md``):
    - Track A (this file) is for create/delete events where the audit row IS the
      activity event. Registered here as PromotionRule entries.
    - Track B is for domain-rich verbs needing structured metadata. The product's
      service code calls ``record_activity()`` directly. Examples:
        * Manifest's signing.* verbs (status transitions need from/to in metadata).
        * Helm's workflow.transitioned (StatusHistory row carries the from/to,
          but the auto-audit snapshot doesn't expose it cleanly).
      These verbs are NOT registered as PromotionRules here.

Each ``_register_<product>_promotions()`` function below is intentionally a stub in this
keel.activity initial scaffolding — products fill in their own rules in Phase 1A and 1C
weeks. The stubs document the expected verb set per product so a reader can see the
shape of the eventual catalog.
"""
from __future__ import annotations

import logging

from django.apps import apps

logger = logging.getLogger(__name__)


def register_all_promotions() -> None:
    """Called from ``ActivityConfig.ready()``. Registers per-product rules conditionally
    on the product's app being installed."""
    if apps.is_installed('helm.tasks') or apps.is_installed('tasks'):
        _register_helm_promotions()
    if apps.is_installed('manifest.signatures') or apps.is_installed('signatures'):
        _register_manifest_promotions()
    if apps.is_installed('beacon.interactions') or apps.is_installed('interactions'):
        _register_beacon_promotions()
    if apps.is_installed('lookout.tracking') or apps.is_installed('tracking'):
        _register_lookout_promotions()
    if apps.is_installed('harbor.applications') or apps.is_installed('applications'):
        _register_harbor_promotions()
    if apps.is_installed('bounty.opportunities') or apps.is_installed('opportunities'):
        _register_bounty_promotions()
    if apps.is_installed('admiralty.foia') or apps.is_installed('foia'):
        _register_admiralty_promotions()
    if apps.is_installed('purser.programs') or apps.is_installed('programs'):
        _register_purser_promotions()
    if apps.is_installed('yeoman'):
        _register_yeoman_promotions()


# ---------------------------------------------------------------------------
# Per-product registration. Phase 1A wires Helm + Manifest + Beacon (Weeks 2-4).
# Phase 1C wires the remaining 6 products. The function bodies below are stubs;
# real rule definitions land in the product wiring weeks.
# ---------------------------------------------------------------------------


def _register_helm_promotions() -> None:
    """Helm tasks Track A rules.

    Phase 1A Week 2 fills this in. Anticipated verbs (Track A):
        - collab.added: ProjectCollaborator create
        - collab.removed: ProjectCollaborator delete
        - diligence.note_posted: TaskComment create
        - diligence.attachment_uploaded: ProjectAttachment create (when Helm adopts AbstractAttachment)
        - lifecycle.archived: Project transitions to archived (via WorkflowEngine; may move to Track B)

    Track B verbs (called from Helm services, not registered here):
        - workflow.transitioned: tasks.services.transition_status() emits this with from/to.
    """
    logger.debug('keel.activity: helm promotion rules not yet registered (Phase 1A Week 2)')


def _register_manifest_promotions() -> None:
    """Manifest signing Track A rules.

    Phase 1A Week 3 fills this in. Per spike findings (MIGRATION-NOTES.md), almost ALL
    Manifest verbs are Track B because SigningStep status diffs aren't carried in the
    audit row's snapshot. The signature-service layer calls ``record_activity()`` directly.

    Anticipated Track A entries (sparse):
        - signing.sent_to_manifest: SigningPacket create — packet creation IS the handoff event.

    Track B verbs (called from manifest/signatures/services.py):
        - signing.next_signer_active (with recipient_resolver to route to next signer)
        - signing.signed
        - signing.declined
        - signing.reminder_sent
        - signing.packet_completed
        - signing.packet_cancelled
        - signing.handoff_failed
    """
    logger.debug('keel.activity: manifest promotion rules not yet registered (Phase 1A Week 3)')


def _register_beacon_promotions() -> None:
    """Beacon interaction Track A rules.

    Phase 1A Week 4 fills this in alongside the Beacon migration (Follow → Watcher,
    ActivityLog → stub-tier Activity). Anticipated verbs:
        - interaction.logged: Interaction create. Visibility is callable — downgrades to
          'stub' when the originating zone is more restricted than SHARED.
        - interaction.attachment_added: InteractionAttachment create. Same zone callable.
        - interaction.participant_added: InteractionParticipant create.

    The Follow → Watcher data migration runs as part of Week 4, in
    beacon/interactions/migrations/. ActivityLog → Activity(visibility=stub) data migration
    runs in the same wave.
    """
    logger.debug('keel.activity: beacon promotion rules not yet registered (Phase 1A Week 4)')


def _register_lookout_promotions() -> None:
    """Lookout tracking Track A rules. Phase 1C."""
    logger.debug('keel.activity: lookout promotion rules not yet registered (Phase 1C)')


def _register_harbor_promotions() -> None:
    """Harbor applications Track A rules. Phase 1C."""
    logger.debug('keel.activity: harbor promotion rules not yet registered (Phase 1C)')


def _register_bounty_promotions() -> None:
    """Bounty opportunities Track A rules. Phase 1C."""
    logger.debug('keel.activity: bounty promotion rules not yet registered (Phase 1C)')


def _register_admiralty_promotions() -> None:
    """Admiralty FOIA Track A rules. Phase 1C.

    Net new opportunity: Admiralty has zero notification types registered today. Wiring
    promotion rules for FOIARequestStatusHistory transitions auto-fans notifications via
    the new path — surfaces statutory-deadline notifications that don't exist today.
    """
    logger.debug('keel.activity: admiralty promotion rules not yet registered (Phase 1C)')


def _register_purser_promotions() -> None:
    """Purser submissions Track A rules. Phase 1C.

    Maps existing 8 notification types to verbs (see verb-catalog-v1.md mapping table).
    """
    logger.debug('keel.activity: purser promotion rules not yet registered (Phase 1C)')


def _register_yeoman_promotions() -> None:
    """Yeoman invitations Track A rules. Phase 1C.

    Yeoman also gets net-new helm-feed wiring in Phase 1C (currently pending per CLAUDE.md).
    """
    logger.debug('keel.activity: yeoman promotion rules not yet registered (Phase 1C)')
