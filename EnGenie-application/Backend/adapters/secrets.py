"""
adapters/secrets.py — At-rest encryption for API keys in the `settings` table.

Mirror of the desktop app's src-tauri/src/config/secrets.rs. Both sides read
and write the SAME rows in studio.db, so the wire format must match exactly:

    dpapi:<base64 of a Windows DPAPI blob>

Encryption is Windows DPAPI (CryptProtectData/CryptUnprotectData) reached
through ctypes — no pip dependency. The key is held by Windows and tied to
the logged-in user account, so studio.db copied to another machine, or read
as a different Windows user, does not give up the API keys.

Deliberately not an AES key embedded in the source: a key shipped alongside
the data it protects is obfuscation, not encryption.

Change this file and secrets.rs together. tests/test_secrets.py verifies the
round-trip and the legacy-plaintext path; it also decrypts a blob produced by
the Rust side when one is available.
"""

from __future__ import annotations

import base64
import ctypes
import sys
from ctypes import wintypes

# Marker prefix for an encrypted value. A stored value WITHOUT this prefix is
# legacy plaintext, written before encryption existed.
ENC_PREFIX = 'dpapi:'

# App-specific entropy mixed into the blob. Must byte-match ENTROPY in
# secrets.rs or nothing either side writes will decrypt on the other.
ENTROPY = b'enstudio.api_key.v1'

IS_WINDOWS = sys.platform == 'win32'


def is_secret_key(field: str) -> bool:
    """True for settings keys whose value is a credential.

    Covers the fixed provider keys and the dynamic custom_<id>_api_key rows.
    Mirrors is_secret_key() in secrets.rs.
    """
    return field.endswith('_api_key')


if IS_WINDOWS:
    class _DataBlob(ctypes.Structure):
        _fields_ = [('cbData', wintypes.DWORD),
                    ('pbData', ctypes.POINTER(ctypes.c_char))]

    # CRYPTPROTECT_UI_FORBIDDEN — never prompt; fail instead. Extraction runs
    # headless under the Tauri sidecar, where a modal would hang the process.
    _UI_FORBIDDEN = 0x1

    _crypt32 = ctypes.WinDLL('crypt32')
    _kernel32 = ctypes.WinDLL('kernel32')

    def _blob(data: bytes) -> _DataBlob:
        buf = ctypes.create_string_buffer(data, len(data))
        return _DataBlob(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def _take(out: _DataBlob) -> bytes:
        """Copy an output blob out and LocalFree the DPAPI allocation."""
        try:
            return ctypes.string_at(out.pbData, out.cbData)
        finally:
            _kernel32.LocalFree(out.pbData)

    def _protect(plain: bytes) -> bytes:
        out = _DataBlob()
        ok = _crypt32.CryptProtectData(
            ctypes.byref(_blob(plain)), None, ctypes.byref(_blob(ENTROPY)),
            None, None, _UI_FORBIDDEN, ctypes.byref(out),
        )
        if not ok:
            raise OSError('CryptProtectData failed')
        return _take(out)

    def _unprotect(cipher: bytes) -> bytes:
        out = _DataBlob()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(_blob(cipher)), None, ctypes.byref(_blob(ENTROPY)),
            None, None, _UI_FORBIDDEN, ctypes.byref(out),
        )
        if not ok:
            raise OSError('CryptUnprotectData failed')
        return _take(out)


def encrypt_secret(plain: str) -> str:
    """Encrypt a secret for storage. Returns the `dpapi:<base64>` wire form.

    Non-Windows has no DPAPI, so the value is returned unchanged rather than
    pretending to encrypt it. The app is Windows-only in practice; this is a
    real gap only if it is ever ported. Mirrors encrypt_secret() in secrets.rs.
    """
    if not plain:
        return ''
    if not IS_WINDOWS:
        return plain
    return ENC_PREFIX + base64.b64encode(_protect(plain.encode('utf-8'))).decode('ascii')


def decrypt_secret(stored: str) -> str:
    """Decrypt a stored value.

    A value without the `dpapi:` prefix is returned as-is — that is a legacy
    plaintext row. Raises on a value that is marked encrypted but cannot be
    read, so a caller never mistakes ciphertext for a usable key.
    """
    if not stored or not stored.startswith(ENC_PREFIX):
        return stored
    if not IS_WINDOWS:
        raise OSError('Encrypted key found but DPAPI is unavailable on this platform')
    raw = base64.b64decode(stored[len(ENC_PREFIX):])
    return _unprotect(raw).decode('utf-8')
