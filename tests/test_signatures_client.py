"""Tests for keel.signatures scaffolding.

Covers the outbound client (send_to_manifest, local_sign), the webhook
signature verification, and the packet_approved signal roundtrip. Uses
a live ManifestHandoff table via pytest-django.
"""
from io import BytesIO
from unittest.mock import patch

import pytest

from django.test import override_settings

from keel.signatures import client
from keel.signatures.models import ManifestHandoff
from keel.signatures.signals import packet_approved
from keel.signatures.views import _verify_signature


# We can't easily instantiate a real source object without a concrete
# product model, so each test uses a stand-in with the minimum shape
# send_to_manifest reads: ._meta.app_label, ._meta.model_name, .pk.
class _FakeMeta:
    def __init__(self, app_label, model_name):
        self.app_label = app_label
        self.model_name = model_name


class _FakeSource:
    def __init__(self, pk='abc-123'):
        self._meta = _FakeMeta('opportunities', 'trackedopportunity')
        self.pk = pk


@pytest.mark.django_db
class TestIsAvailable:
    def test_false_when_unset(self):
        with override_settings(MANIFEST_URL='', MANIFEST_API_TOKEN=''):
            assert client.is_available() is False

    def test_false_when_only_url_set(self):
        with override_settings(MANIFEST_URL='https://manifest.example.com', MANIFEST_API_TOKEN=''):
            assert client.is_available() is False

    def test_true_when_both_set(self):
        with override_settings(
            MANIFEST_URL='https://manifest.example.com',
            MANIFEST_API_TOKEN='sometoken',
        ):
            assert client.is_available() is True


@pytest.mark.django_db
class TestSendToManifest:
    def test_marks_failed_when_manifest_not_configured(self):
        with override_settings(MANIFEST_URL='', MANIFEST_API_TOKEN=''):
            handoff = client.send_to_manifest(
                source_obj=_FakeSource(),
                packet_label='Internal Approval',
                signers=[],
                attachment_model='opportunities.OpportunityAttachment',
                attachment_fk_name='tracked_opportunity',
                on_approved_status='approved',
            )
        assert handoff.status == ManifestHandoff.Status.FAILED
        assert 'not configured' in handoff.error_message.lower()
        # The row is still written so the UI can surface the failure.
        assert ManifestHandoff.objects.filter(pk=handoff.pk).exists()

    def test_marks_sent_on_successful_post(self):
        mock_response = type('R', (), {
            'json': lambda self: {
                'packet_uuid': 'abc-packet',
                'packet_url': 'https://manifest.example.com/packets/abc-packet/',
            },
            'raise_for_status': lambda self: None,
        })()
        with override_settings(
            MANIFEST_URL='https://manifest.example.com',
            MANIFEST_API_TOKEN='tkn',
        ), patch('requests.post', return_value=mock_response) as mock_post:
            handoff = client.send_to_manifest(
                source_obj=_FakeSource(),
                packet_label='Internal Approval',
                signers=[{'email': 'a@b.com'}],
                attachment_model='opportunities.OpportunityAttachment',
                attachment_fk_name='tracked_opportunity',
                on_approved_status='approved',
            )
        assert handoff.status == ManifestHandoff.Status.SENT
        assert handoff.manifest_packet_uuid == 'abc-packet'
        assert handoff.manifest_url.endswith('/abc-packet/')
        mock_post.assert_called_once()

    def test_marks_failed_on_network_error(self):
        def _boom(*a, **kw):
            raise ConnectionError('network unreachable')
        with override_settings(
            MANIFEST_URL='https://manifest.example.com',
            MANIFEST_API_TOKEN='tkn',
        ), patch('requests.post', side_effect=_boom):
            handoff = client.send_to_manifest(
                source_obj=_FakeSource(),
                packet_label='x',
                signers=[],
                attachment_model='opportunities.OpportunityAttachment',
                attachment_fk_name='tracked_opportunity',
                on_approved_status='approved',
            )
        assert handoff.status == ManifestHandoff.Status.FAILED
        assert 'network unreachable' in handoff.error_message


@pytest.mark.django_db
class TestLocalSign:
    def test_records_local_signed_handoff_and_fires_signal(self):
        """When Manifest isn't deployed, local_sign fires the same signal."""
        captured = {}

        def _receiver(sender, handoff, source_obj, signed_pdf, **kwargs):
            captured['handoff'] = handoff
            captured['source_obj'] = source_obj
            captured['signed_pdf'] = signed_pdf

        packet_approved.connect(_receiver)
        try:
            # We patch resolve_source so the signal handler has something
            # to send alongside the handoff row. The real product receiver
            # will look up a live DB row.
            source = _FakeSource()
            with patch.object(ManifestHandoff, 'resolve_source', return_value=source):
                handoff = client.local_sign(
                    source_obj=source,
                    signed_pdf=BytesIO(b'fake pdf bytes'),
                    attachment_model='opportunities.OpportunityAttachment',
                    attachment_fk_name='tracked_opportunity',
                    on_approved_status='approved',
                    packet_label='Internal Approval (local)',
                )
        finally:
            packet_approved.disconnect(_receiver)

        assert handoff.status == ManifestHandoff.Status.LOCAL_SIGNED
        assert handoff.signed_at is not None
        assert captured['handoff'] == handoff
        assert captured['source_obj'] is source


class TestWebhookSignature:
    def test_rejects_when_secret_unset(self):
        with override_settings(MANIFEST_WEBHOOK_SECRET=''):
            assert _verify_signature(b'body', 'sha256=whatever') is False

    def test_rejects_when_header_missing(self):
        with override_settings(MANIFEST_WEBHOOK_SECRET='s3cr3t'):
            assert _verify_signature(b'body', '') is False

    def test_accepts_matching_signature(self):
        import hashlib
        import hmac
        secret = 's3cr3t'
        body = b'payload'
        digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        with override_settings(MANIFEST_WEBHOOK_SECRET=secret):
            assert _verify_signature(body, f'sha256={digest}') is True

    def test_rejects_mismatched_signature(self):
        with override_settings(MANIFEST_WEBHOOK_SECRET='s3cr3t'):
            assert _verify_signature(b'body', 'sha256=deadbeef') is False


@pytest.mark.django_db
class TestManifestHandoffModel:
    def test_source_label_format(self):
        handoff = ManifestHandoff.objects.create(
            source_app_label='opportunities',
            source_model='trackedopportunity',
            source_pk='abc-123',
            attachment_model='opportunities.OpportunityAttachment',
            attachment_fk_name='tracked_opportunity',
            on_approved_status='approved',
        )
        assert handoff.source_label == 'opportunities.trackedopportunity:abc-123'

    def test_default_status_is_pending(self):
        handoff = ManifestHandoff.objects.create(
            source_app_label='a', source_model='b', source_pk='c',
            attachment_model='a.b', attachment_fk_name='fk',
            on_approved_status='s',
        )
        assert handoff.status == ManifestHandoff.Status.PENDING
