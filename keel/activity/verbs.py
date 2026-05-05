"""Verb catalog for keel.activity.

Companion to ``/Users/dok/.gstack/projects/CT/verb-catalog-v1.md`` — kept in sync at
release boundaries. The verb code is the immutable contract; the display label can change
freely. Never rename a verb; only add new and deprecate old.

Format: dotted snake_case (``namespace.verb``), past-tense, third-person.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Verb:
    """Definition of an activity verb.

    Fields:
        code: the immutable identifier (e.g. ``'collab.added'``).
        label: human-readable label for /notifications/preferences/ rendering.
        default_visibility: one of VISIBILITY_CHOICES from models.py. Promotion rules
            may override per-row via a callable visibility, but the default lives here.
        default_notify: True = subscribers receive a notification by default.
        description: short prose description for the catalog UI.
        recipient_resolver_required: True iff this verb's notification dispatch needs a
            verb-specific resolver (e.g. ``signing.next_signer_active`` routes to the
            new active signer, not collaborators-of-target). Without a resolver, dispatch
            falls back to the standard collab+watcher+role resolution.
    """
    code: str
    label: str
    default_visibility: str = 'collaborators'
    default_notify: bool = True
    description: str = ''
    recipient_resolver_required: bool = False


# ---------------------------------------------------------------------------
# Catalog. Mirrors verb-catalog-v1.md. Adding a verb = adding an entry here.
# ---------------------------------------------------------------------------
VERB_CATALOG: dict[str, Verb] = {}


def _register(verb: Verb):
    """Register a verb in the catalog. Called only at module import time."""
    if verb.code in VERB_CATALOG:
        raise ValueError(f'Duplicate verb code: {verb.code}')
    VERB_CATALOG[verb.code] = verb


# ── lifecycle.* — record creation, claim, archive ─────────────────────────
_register(Verb('lifecycle.created', 'Record created',
               default_notify=False,
               description='A new record was created. Often noisy; most products skip promoting this.'))
_register(Verb('lifecycle.claimed', 'Record claimed',
               description='A user took ownership via AbstractAssignment (CLAIMED type).'))
_register(Verb('lifecycle.assigned', 'Record assigned',
               description='A manager assigned the record to a user (MANAGER_ASSIGNED type).'))
_register(Verb('lifecycle.released', 'Record released',
               description='The owner released the claim.'))
_register(Verb('lifecycle.reassigned', 'Record reassigned',
               description='Ownership moved between users.'))
_register(Verb('lifecycle.archived', 'Record archived',
               default_notify=False,
               description='Record archived via ArchivableMixin.'))
_register(Verb('lifecycle.unarchived', 'Record unarchived',
               default_notify=False))
_register(Verb('lifecycle.deleted', 'Record deleted',
               default_visibility='staff', default_notify=False))


# ── collab.* — collaborator membership ────────────────────────────────────
_register(Verb('collab.added', 'Collaborator added',
               description='Collaborator added (internal user OR external email). action GFK = the Collaborator row.'))
_register(Verb('collab.invited', 'External collaborator invited',
               description='External-email invite sent (no KeelUser linked yet).'))
_register(Verb('collab.accepted', 'Invitation accepted',
               description='External invitee accepted and linked a KeelUser.'))
_register(Verb('collab.removed', 'Collaborator removed'))
_register(Verb('collab.role_changed', 'Collaborator role changed',
               description='metadata: {from_role, to_role}.'))


# ── diligence.* — notes and attachments ────────────────────────────────────
_register(Verb('diligence.note_posted', 'Note posted',
               description='A new note created. action GFK = the Note row.'))
_register(Verb('diligence.note_pinned', 'Note pinned', default_notify=False))
_register(Verb('diligence.note_unpinned', 'Note unpinned', default_notify=False))
_register(Verb('diligence.attachment_uploaded', 'Attachment uploaded'))
_register(Verb('diligence.attachment_replaced', 'Attachment replaced',
               description='Existing attachment replaced (new version).'))
_register(Verb('diligence.attachment_removed', 'Attachment removed',
               default_notify=False))


# ── interaction.* — Beacon-specific (subsumes Beacon's Interaction + ActivityLog) ──
_register(Verb('interaction.logged', 'Interaction logged',
               description='Beacon Interaction row created. action GFK = the Interaction. '
                           'Visibility downgrades to stub when the originating zone is more '
                           'restricted than the viewer\'s.'))
_register(Verb('interaction.attachment_added', 'Interaction attachment added',
               default_notify=False))
_register(Verb('interaction.participant_added', 'Interaction participant added',
               default_notify=False))


# ── workflow.* — status transitions ────────────────────────────────────────
_register(Verb('workflow.transitioned', 'Status changed',
               description='Generic status change. metadata: {from_status, to_status, comment}. '
                           'action GFK = the StatusHistory row.'))
_register(Verb('workflow.deadline_approaching', 'Deadline approaching',
               description='Fired by scheduled keel.scheduling job when statutory deadline is N days out.'))
_register(Verb('workflow.deadline_passed', 'Deadline passed',
               default_visibility='staff'))


# ── signing.* — Manifest packet lifecycle (all Track B — explicit record_activity()) ──
_register(Verb('signing.sent_to_manifest', 'Sent to Manifest',
               description='Source product handed off to Manifest. metadata: {packet_uuid, signer_count}.'))
_register(Verb('signing.next_signer_active', 'Your turn to sign',
               recipient_resolver_required=True,
               description='Previous signer completed; the next signer is now active. Recipient is the '
                           'newly-active signer (NOT collaborators-of-target). Dispatch routes via '
                           'NotificationType.recipient_resolver. Maps to Manifest\'s legacy signature_required type.'))
_register(Verb('signing.signed', 'Signer signed',
               description='A signer signed (past action). metadata: {signer_email, step_index}.'))
_register(Verb('signing.declined', 'Signer declined',
               description='ACTIVE → DECLINED transition. metadata: {signer_email, reason}.'))
_register(Verb('signing.reminder_sent', 'Signing reminder sent',
               default_notify=False))
_register(Verb('signing.packet_completed', 'Packet completed',
               description='All signers done; signed PDF returned. action GFK = the MANIFEST_SIGNED Attachment row.'))
_register(Verb('signing.packet_cancelled', 'Packet cancelled'))
_register(Verb('signing.handoff_failed', 'Manifest handoff failed',
               default_visibility='staff',
               description='Outbound call to Manifest failed; retry control surfaced. Staff-visible system error.'))


# ── cross.* — cross-product flows ──────────────────────────────────────────
_register(Verb('cross.intake_received', 'Cross-product intake received',
               description='This product received a record from a peer\'s intake API. '
                           'metadata: {source_product, source_url, source_label}.'))
_register(Verb('cross.exported_to', 'Exported to peer',
               description='This record was pushed to a peer (Bounty win → Harbor grant, '
                           'Beacon contact → Yeoman invitation). metadata: {dest_product, dest_url}.'))
_register(Verb('cross.peer_unreachable', 'Peer unreachable',
               default_visibility='staff', default_notify=False))


# ── foia.* — FOIA export ────────────────────────────────────────────────────
_register(Verb('foia.registered', 'Registered for FOIA',
               default_visibility='staff', default_notify=False))
_register(Verb('foia.exported', 'Exported via FOIA',
               default_visibility='staff',
               description='Record bundled into a FOIA response by Admiralty. action GFK = FOIAExportItem.'))
_register(Verb('foia.purged', 'Purged after retention expiry',
               default_visibility='staff', default_notify=False))


# ── comms.* — emails and messages (when keel.comms is wired) ────────────────
_register(Verb('comms.email_sent', 'Email sent',
               default_notify=False,
               description='Outbound email tied to this record via MailboxAddress. action GFK = Message row.'))
_register(Verb('comms.email_received', 'Email received',
               description='Inbound email arrived for this record. action GFK = Message row.'))
_register(Verb('comms.email_bounced', 'Email bounced',
               default_visibility='staff'))


# ── compliance.* — Purser-style obligation tracking ────────────────────────
_register(Verb('compliance.variance_flagged', 'Compliance variance flagged',
               description='Purser submission has a budget variance. Maps to legacy purser_variance_alert.'))
_register(Verb('compliance.reminder', 'Compliance reminder',
               description='Maps to legacy purser_compliance_reminder.'))


# ── system.* — automated activity, no human actor ──────────────────────────
_register(Verb('system.imported', 'Bulk import touched record',
               default_visibility='staff', default_notify=False))
_register(Verb('system.synced', 'Scheduled job touched record',
               default_visibility='staff', default_notify=False))
_register(Verb('system.webhook_received', 'External webhook received',
               default_visibility='staff', default_notify=False))
_register(Verb('system.aggregator_imported', 'Helm aggregator import',
               default_visibility='staff', default_notify=False,
               description='ONE row per RUN, not per record. metadata.count = N.'))


def get_verb(code: str) -> Optional[Verb]:
    """Look up a verb by code. Returns None if not registered."""
    return VERB_CATALOG.get(code)


def all_verbs() -> list[Verb]:
    """Return all registered verbs, sorted by code."""
    return sorted(VERB_CATALOG.values(), key=lambda v: v.code)
