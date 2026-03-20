"""
Keel File Scanning — ClamAV integration for upload malware detection.

Usage:
    from keel.security.scanning import scan_file

    # In a form or view:
    if not scan_file(uploaded_file):
        raise ValidationError('File failed security scan.')

Configure in settings.py:
    KEEL_FILE_SCANNING_ENABLED = True  # default: True in production
    KEEL_CLAMAV_SOCKET = '/var/run/clamav/clamd.ctl'  # or 'tcp://localhost:3310'
    KEEL_ALLOWED_UPLOAD_EXTENSIONS = ['.pdf', '.docx', '.xlsx', ...]  # default list below
    KEEL_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB default
"""
import logging
import os
import socket

from django.conf import settings
from django.core.exceptions import ValidationError

logger = logging.getLogger('keel.security')

DEFAULT_ALLOWED_EXTENSIONS = [
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.rtf',
    '.odt', '.ods', '.ppt', '.pptx',
    '.png', '.jpg', '.jpeg', '.gif', '.tiff', '.svg',
    '.zip', '.gz', '.tar',
]

DEFAULT_MAX_SIZE = 10 * 1024 * 1024  # 10MB


def _get_allowed_extensions():
    return getattr(settings, 'KEEL_ALLOWED_UPLOAD_EXTENSIONS', DEFAULT_ALLOWED_EXTENSIONS)


def _get_max_size():
    return getattr(settings, 'KEEL_MAX_UPLOAD_SIZE', DEFAULT_MAX_SIZE)


def _is_scanning_enabled():
    if getattr(settings, 'DEBUG', False):
        return getattr(settings, 'KEEL_FILE_SCANNING_ENABLED', False)
    return getattr(settings, 'KEEL_FILE_SCANNING_ENABLED', True)


def validate_file_extension(uploaded_file):
    """Check file extension against allowlist."""
    ext = os.path.splitext(uploaded_file.name)[1].lower()
    allowed = _get_allowed_extensions()
    if ext not in allowed:
        raise ValidationError(
            f'File type "{ext}" is not allowed. '
            f'Allowed types: {", ".join(allowed)}'
        )


def validate_file_size(uploaded_file):
    """Check file doesn't exceed max upload size."""
    max_size = _get_max_size()
    if uploaded_file.size > max_size:
        max_mb = max_size / (1024 * 1024)
        file_mb = uploaded_file.size / (1024 * 1024)
        raise ValidationError(
            f'File size ({file_mb:.1f} MB) exceeds the maximum of {max_mb:.0f} MB.'
        )


def scan_with_clamav(file_data):
    """Scan file data with ClamAV via socket.

    Returns (is_clean, message).
    """
    clamav_socket = getattr(settings, 'KEEL_CLAMAV_SOCKET', '/var/run/clamav/clamd.ctl')

    try:
        if clamav_socket.startswith('tcp://'):
            # TCP connection
            host_port = clamav_socket[6:]
            host, port = host_port.rsplit(':', 1)
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect((host, int(port)))
        else:
            # Unix socket
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(30)
            sock.connect(clamav_socket)

        # Send INSTREAM command
        sock.send(b'zINSTREAM\x00')

        # Send data in chunks
        chunk_size = 2048
        for i in range(0, len(file_data), chunk_size):
            chunk = file_data[i:i + chunk_size]
            sock.send(len(chunk).to_bytes(4, byteorder='big'))
            sock.send(chunk)

        # End of stream
        sock.send(b'\x00\x00\x00\x00')

        # Read response
        response = sock.recv(4096).decode('utf-8', errors='replace').strip('\x00').strip()
        sock.close()

        if 'OK' in response and 'FOUND' not in response:
            return True, 'Clean'
        elif 'FOUND' in response:
            logger.critical(
                'Malware detected in uploaded file: %s',
                response,
                extra={'security_event': 'malware_detected', 'scan_result': response},
            )
            return False, response
        else:
            logger.warning('Unexpected ClamAV response: %s', response)
            return True, f'Unknown response: {response}'

    except (ConnectionRefusedError, FileNotFoundError, OSError) as e:
        logger.error('ClamAV connection failed: %s', str(e))
        # Fail-open or fail-closed based on settings
        fail_closed = getattr(settings, 'KEEL_CLAMAV_FAIL_CLOSED', True)
        if fail_closed:
            return False, f'Scan unavailable: {e}'
        return True, f'Scan skipped (unavailable): {e}'


def scan_file(uploaded_file):
    """Full file validation pipeline: extension + size + malware scan.

    Returns True if file is safe. Raises ValidationError if not.
    """
    validate_file_extension(uploaded_file)
    validate_file_size(uploaded_file)

    if _is_scanning_enabled():
        # Read file data for scanning
        file_data = uploaded_file.read()
        uploaded_file.seek(0)  # Reset for downstream consumers

        is_clean, message = scan_with_clamav(file_data)
        if not is_clean:
            raise ValidationError(
                'File failed security scan. Please contact support if you believe this is an error.'
            )

    return True


class FileSecurityValidator:
    """Django form/model field validator for file uploads.

    Usage in a model:
        file = models.FileField(validators=[FileSecurityValidator()])

    Or in a form clean method:
        def clean_file(self):
            f = self.cleaned_data['file']
            FileSecurityValidator()(f)
            return f
    """

    def __call__(self, uploaded_file):
        scan_file(uploaded_file)

    def deconstruct(self):
        return ('keel.security.scanning.FileSecurityValidator', [], {})
