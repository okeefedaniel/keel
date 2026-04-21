"""keel.signatures — shared Manifest signing-handoff scaffolding.

Provides the outbound helper (``send_to_manifest``) and the inbound
completion webhook + signal that let any DockLabs product ask Manifest
to shepherd a document through a signing flow and get back a
product-specific "mark as approved + file the signed PDF" roundtrip.

Scope today:
  * ``ManifestHandoff`` — local back-pointer table (no cross-DB FK).
  * ``client.send_to_manifest`` + ``client.is_available`` — outbound.
  * ``client.local_sign`` — standalone-mode fallback when Manifest
    isn't deployed.
  * ``signals.packet_approved`` — fires when a handoff completes;
    products connect a receiver to attach the signed PDF and transition
    the source object's status.
  * ``/keel/signatures/webhook/`` — inbound completion endpoint that
    Manifest POSTs to when a packet is signed.

Out of scope (deferred): the per-product ``signatures/`` app
dedup documented in the original placeholder. That extraction (moving
harbor + manifest ``services.py`` behind ``keel.signatures.services``)
is still blocked on migration strategy + test coverage; see the plan in
the repo history for 0.13.0. The scaffolding here treats Manifest as a
black-box HTTP service and does not depend on that dedup landing.
"""
default_app_config = 'keel.signatures.apps.KeelSignaturesConfig'

__all__ = []
