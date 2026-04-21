"""Signals emitted by keel.signatures."""
import django.dispatch


# Fires when a ManifestHandoff completes — either via the inbound
# Manifest webhook or via the standalone local_sign() fallback.
#
# Args:
#   sender: the source object's Django model class.
#   handoff: the ManifestHandoff row.
#   source_obj: the resolved source object (e.g. TrackedOpportunity).
#   signed_pdf: an open file-like object with the signed PDF bytes.
#       Products write this to their Attachment collection.
packet_approved = django.dispatch.Signal()
