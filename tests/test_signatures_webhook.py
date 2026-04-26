"""SSRF + size-cap defenses on the inbound Manifest signing webhook."""
from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch

import pytest
from django.test import RequestFactory, override_settings

from keel.security.http import UnsafeURLError


SECRET = 'test-webhook-secret'


def _signed_request(payload: dict):
    body = json.dumps(payload).encode()
    sig = 'sha256=' + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    rf = RequestFactory()
    return rf.post(
        '/keel/signatures/webhook/',
        data=body,
        content_type='application/json',
        HTTP_X_MANIFEST_SIGNATURE=sig,
    )


@override_settings(MANIFEST_WEBHOOK_SECRET=SECRET)
@pytest.mark.django_db
def test_unsafe_url_marks_handoff_failed_returns_400():
    from keel.signatures.models import ManifestHandoff
    from keel.signatures.views import webhook

    handoff = ManifestHandoff.objects.create(
        source_app_label='signatures',
        source_model='dummy',
        source_pk='1',
        manifest_packet_uuid='pkt-1',
        attachment_model='signatures.Dummy',
        attachment_fk_name='dummy',
        on_approved_status='approved',
        status=ManifestHandoff.Status.SENT,
    )

    request = _signed_request({
        'handoff_id': str(handoff.pk),
        'packet_uuid': 'pkt-1',
        'signed_pdf_url': 'http://169.254.169.254/latest/meta-data/',
    })

    with patch('keel.security.http.safe_get', side_effect=UnsafeURLError('blocked')):
        response = webhook(request)

    assert response.status_code == 400
    handoff.refresh_from_db()
    assert handoff.status == ManifestHandoff.Status.FAILED
    assert 'Unsafe' in handoff.error_message
