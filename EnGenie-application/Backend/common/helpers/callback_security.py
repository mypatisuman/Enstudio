"""
Shared-secret HMAC signing/verification for server-to-server async callbacks.

Both the dispatcher (EnGenie API) and the worker share CALLBACK_SECRET. The
signature is computed over `timestamp + "." + raw_body`, which binds the body
to a point in time and lets the receiver reject stale/replayed callbacks.

Headers used on the wire:
    X-Timestamp : unix epoch seconds (as a string) when the payload was signed
    X-Signature : hex HMAC-SHA256 of the signed message
"""
import hashlib
import hmac
import logging
import os
import time

# 5-minute replay window. A captured callback can't be re-sent after this.
_MAX_SKEW_SECONDS = 300


def _secret() -> bytes:
    """Read the shared secret lazily so env changes/rotation are picked up."""
    secret = os.getenv("CALLBACK_SECRET", "")
    if not secret:
        logging.warning(
            "[CALLBACK_SECURITY] CALLBACK_SECRET is not set — callback "
            "signatures cannot be verified. Set it before enabling the worker."
        )
    return secret.encode()


def sign_payload(raw_body: bytes, timestamp: str) -> str:
    """Return the hex HMAC-SHA256 signature for a raw body at a given timestamp."""
    message = timestamp.encode() + b"." + raw_body
    return hmac.new(_secret(), message, hashlib.sha256).hexdigest()


def verify_signature(raw_body: bytes, timestamp: str, signature: str) -> bool:
    """
    Constant-time verification of an incoming callback.

    Returns False (never raises) on a missing secret, malformed timestamp,
    expired timestamp, or signature mismatch.
    """
    if not _secret():
        return False
    try:
        skew = abs(time.time() - float(timestamp))
    except (TypeError, ValueError):
        return False
    if skew > _MAX_SKEW_SECONDS:
        logging.warning("[CALLBACK_SECURITY] Rejected callback: timestamp skew %.0fs", skew)
        return False
    expected = sign_payload(raw_body, timestamp)
    return hmac.compare_digest(expected, signature or "")
