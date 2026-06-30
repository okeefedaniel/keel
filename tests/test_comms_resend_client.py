"""Unit tests for keel.comms.resend_client.

Covers the security-critical Svix webhook-signature verification. The happy
path is checked against Svix's own published test vector so the test is not
circular — it proves our HMAC matches the Svix spec byte-for-byte.

These are pure-function tests (no Django models), so they run under the keel
test site even though it does not install keel.comms.
"""
import base64
import hashlib
import hmac

from keel.comms import resend_client

# Svix's canonical example (https://docs.svix.com/receiving/verifying-payloads).
_VECTOR_SECRET = 'whsec_MfKQ9r8GKYqrTwjUPD8ILPZIo2LaLaSw'
_VECTOR_ID = 'msg_p5jXN8AQM9LWM0D4loKWxJek'
_VECTOR_TS = '1614265330'
_VECTOR_PAYLOAD = '{"test": 2432232314}'
_VECTOR_SIG = 'v1,g0hM9SsE+OTPJTGt/tmIKtSyZlE3uFJELVlNIOLJ1OE='


def _headers(id_=_VECTOR_ID, ts=_VECTOR_TS, sig=_VECTOR_SIG):
    return {'svix-id': id_, 'svix-timestamp': ts, 'svix-signature': sig}


def test_verifies_svix_canonical_vector():
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, _headers(), _VECTOR_PAYLOAD, now=int(_VECTOR_TS),
    ) is True


def test_accepts_bytes_body():
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, _headers(), _VECTOR_PAYLOAD.encode('utf-8'), now=int(_VECTOR_TS),
    ) is True


def test_rejects_tampered_payload():
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, _headers(), '{"test": 9999999999}', now=int(_VECTOR_TS),
    ) is False


def test_rejects_wrong_signature():
    bad = _headers(sig='v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=')
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, bad, _VECTOR_PAYLOAD, now=int(_VECTOR_TS),
    ) is False


def test_rejects_missing_headers():
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, {'svix-id': _VECTOR_ID}, _VECTOR_PAYLOAD, now=int(_VECTOR_TS),
    ) is False


def test_rejects_stale_timestamp():
    # Same valid signature, but evaluated well outside the 5-minute window.
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, _headers(), _VECTOR_PAYLOAD, now=int(_VECTOR_TS) + 3600,
    ) is False


def test_rejects_empty_secret():
    assert resend_client.verify_webhook_signature(
        '', _headers(), _VECTOR_PAYLOAD, now=int(_VECTOR_TS),
    ) is False


def test_accepts_multiple_signatures_when_one_matches():
    # Svix may send several space-delimited signatures during secret rotation.
    multi = f'v1,AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA= {_VECTOR_SIG}'
    assert resend_client.verify_webhook_signature(
        _VECTOR_SECRET, _headers(sig=multi), _VECTOR_PAYLOAD, now=int(_VECTOR_TS),
    ) is True


def test_matches_independent_hmac_for_generated_secret():
    # Non-vector check with a freshly minted secret, signing independently.
    raw_key = b'a-random-signing-key-32-bytes!!!'
    secret = 'whsec_' + base64.b64encode(raw_key).decode()
    msg_id, ts, body = 'msg_abc', '1700000000', '{"type":"email.received"}'
    signed = f'{msg_id}.{ts}.{body}'.encode()
    sig = base64.b64encode(hmac.new(raw_key, signed, hashlib.sha256).digest()).decode()
    headers = {'svix-id': msg_id, 'svix-timestamp': ts, 'svix-signature': f'v1,{sig}'}
    assert resend_client.verify_webhook_signature(
        secret, headers, body, now=int(ts),
    ) is True
