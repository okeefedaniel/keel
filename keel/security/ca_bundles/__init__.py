"""CA bundles shipped with keel for hosts that serve incomplete TLS chains.

Usage in a product::

    from keel.security.ca_bundles import cga_ct_gov_bundle
    resp = requests.get(url, timeout=30, verify=cga_ct_gov_bundle())
"""
from pathlib import Path

_HERE = Path(__file__).parent


def cga_ct_gov_bundle() -> str:
    """Return the path to a CA bundle that validates www.cga.ct.gov.

    www.cga.ct.gov serves only its leaf cert in the TLS handshake and omits
    the Go Daddy Secure Certificate Authority G2 intermediate. Default
    clients (python-requests, urllib3) fall back to certifi which carries
    GoDaddy roots but not intermediates, so verification fails with
    CERTIFICATE_VERIFY_FAILED.

    This bundle is certifi + the G2 intermediate, combined once at build
    time. Returning its absolute path lets callers pass it directly to
    ``requests.get(..., verify=...)`` without loading the file themselves.
    """
    return str(_HERE / 'cga_ct_gov.pem')
