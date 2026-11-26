"""
JWT helpers, authentication dependencies, file validation, and login decorator.
All security primitives for the Engenie backend live here.
"""
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from functools import wraps

import jwt
import json

from common.config.settings import JWT_ALGORITHM, JWT_EXPIRATION_HOURS, JWT_SECRET_KEY


# ══════════════════════════════════════════════════════════════════════════
# FILE NAME SANITISATION
# ══════════════════════════════════════════════════════════════════════════

def secure_filename(filename: str) -> str:
    """Sanitize a filename — strips anything that isn't alphanumeric, _, -, or dot."""
    filename = re.sub(r'[^A-Za-z0-9_.\-]', '', filename.replace(' ', '_'))
    return filename


# ══════════════════════════════════════════════════════════════════════════
# FILE UPLOAD VALIDATION
# ══════════════════════════════════════════════════════════════════════════

MAX_FILE_SIZE_MB = 100
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024  # 100 MB

# Allowed file extensions → expected MIME types
ALLOWED_FILE_TYPES: dict[str, list[str]] = {
    '.pdf':  ['application/pdf'],
    '.doc':  ['application/msword'],
    '.docx': ['application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
    '.txt':  ['text/plain'],
    '.png':  ['image/png'],
    '.jpg':  ['image/jpeg'],
    '.jpeg': ['image/jpeg'],
    '.gif':  ['image/gif'],
    '.json': ['application/json'],
    '.csv':  ['text/csv', 'application/csv', 'text/plain'],
}

# Magic-number (binary signature) map for common binary types
FILE_SIGNATURES: dict[str, list[bytes]] = {
    '.pdf':  [b'%PDF'],
    '.png':  [b'\x89PNG\r\n\x1a\n'],
    '.jpg':  [b'\xff\xd8\xff'],
    '.jpeg': [b'\xff\xd8\xff'],
    '.gif':  [b'GIF87a', b'GIF89a'],
    '.doc':  [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],  # OLE compound document
    '.docx': [b'PK\x03\x04'],                          # ZIP/OOXML
    # .txt, .csv, .json — no reliable magic number
}


def validate_uploaded_file(
    file,
    allowed_extensions: list[str] | None = None,
    max_size_bytes: int = MAX_FILE_SIZE_BYTES,
) -> dict:
    """
    Securely validate an uploaded file.

    Args:
        file: UploadFile object from FastAPI.
        allowed_extensions: Whitelist of extensions (e.g. ['.pdf', '.docx']).
                            Defaults to all keys in ALLOWED_FILE_TYPES.
        max_size_bytes: Maximum allowed file size in bytes.

    Returns:
        dict with keys: valid (bool), error (str|None), filename (str), extension (str).
    """
    if not file or not file.filename:
        return {'valid': False, 'error': 'No file provided', 'filename': None, 'extension': None}

    filename = secure_filename(file.filename)
    if not filename:
        return {'valid': False, 'error': 'Invalid filename', 'filename': None, 'extension': None}

    ext = os.path.splitext(filename)[1].lower()
    allowed_exts = allowed_extensions if allowed_extensions else list(ALLOWED_FILE_TYPES.keys())

    if ext not in allowed_exts:
        return {
            'valid': False,
            'error': f'File type {ext} not allowed. Allowed: {", ".join(allowed_exts)}',
            'filename': filename,
            'extension': ext,
        }

    file_content = file.read()
    file.seek(0)  # reset pointer for downstream consumers

    if len(file_content) > max_size_bytes:
        return {
            'valid': False,
            'error': f'File too large. Maximum size: {max_size_bytes // (1024 * 1024)} MB',
            'filename': filename,
            'extension': ext,
        }

    if len(file_content) == 0:
        return {'valid': False, 'error': 'File is empty', 'filename': filename, 'extension': ext}

    if ext in FILE_SIGNATURES:
        signatures = FILE_SIGNATURES[ext]
        if not any(file_content.startswith(sig) for sig in signatures):
            logging.warning(f"[FILE_VALIDATION] {filename} has mismatched magic number for {ext}")
            return {
                'valid': False,
                'error': 'File content does not match its extension',
                'filename': filename,
                'extension': ext,
            }

    return {'valid': True, 'error': None, 'filename': filename, 'extension': ext}


# ══════════════════════════════════════════════════════════════════════════
# JWT HELPERS
# ══════════════════════════════════════════════════════════════════════════

def generate_jwt_token(user_id: int, username: str) -> str:
    """Generate a signed JWT token for user authentication."""
    payload = {
        "user_id": user_id,
        "username": username,
        "exp": datetime.now(UTC) + timedelta(hours=JWT_EXPIRATION_HOURS),
        "iat": datetime.now(UTC),
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def validate_jwt_token(token: str) -> dict:
    """Validate a JWT token and return the decoded payload or an error dict."""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return {
            "valid": True,
            "user_id": payload["user_id"],
            "username": payload["username"],
        }
    except jwt.ExpiredSignatureError:
        return {"valid": False, "error": "Token expired"}
    except jwt.InvalidTokenError as e:
        return {"valid": False, "error": f"Invalid token: {str(e)}"}


# ══════════════════════════════════════════════════════════════════════════
# AUTH DECORATOR
# ══════════════════════════════════════════════════════════════════════════

def login_required(func_to_decorate):
    """Decorator that validates JWT for FastAPI routes."""
    import asyncio as _asyncio

    @wraps(func_to_decorate)
    async def decorated_function(*args, **kwargs):
        from app.dependencies.auth import get_current_user
        request = kwargs.get('request')
        if request is None:
            for arg in args:
                if hasattr(arg, 'headers'):
                    request = arg
                    break
        validation = get_current_user(request)
        if not validation.get("valid"):
            from fastapi.responses import JSONResponse as _FJR
            return _FJR(
                content={"success": False, "error": validation.get("error")},
                status_code=401
            )
        try:
            from common.helpers.azure_session import get_session
            from common.monitoring.usage import session_analytics
            session = get_session(request)
            session_id = session.get("session_id")
            user_id = validation.get("user_id")
            if user_id and session_id:
                session_analytics.update_session_activity(
                    user_id=str(user_id),
                    session_id=str(session_id),
                    activity_type="api_call",
                    activity_details={"path": str(request.url), "method": request.method}
                )
        except Exception as e:
            logging.error(f"[TRACKING] Failed to update session activity: {e}")

        if _asyncio.iscoroutinefunction(func_to_decorate):
            return await func_to_decorate(*args, **kwargs)
        return func_to_decorate(*args, **kwargs)
    return decorated_function


def optional_login(func_to_decorate):
    """Decorator that validates JWT if provided, but gracefully falls back to a desktop/guest
    session rather than failing with 401. This supports agents migrated from standalone/Electron
    environments while still supporting full user tracking in the web application."""
    import asyncio as _asyncio

    @wraps(func_to_decorate)
    async def decorated_function(*args, **kwargs):
        from app.dependencies.auth import get_current_user
        request = kwargs.get('request')
        if request is None:
            for arg in args:
                if hasattr(arg, 'headers'):
                    request = arg
                    break

        validation = get_current_user(request) if request else {"valid": False}
        user_id = validation.get("user_id") if validation.get("valid") else "desktop_user"

        try:
            from common.helpers.azure_session import get_session
            session = get_session(request)
            if not session.get("user_id"):
                session._data["user_id"] = user_id

            if validation.get("valid") and user_id and session.get("session_id"):
                from common.monitoring.usage import session_analytics
                session_analytics.update_session_activity(
                    user_id=str(user_id),
                    session_id=str(session.get("session_id")),
                    activity_type="api_call",
                    activity_details={"path": str(request.url), "method": request.method}
                )
        except Exception as e:
            logging.debug(f"[OPTIONAL_LOGIN] session setup info: {e}")

        if _asyncio.iscoroutinefunction(func_to_decorate):
            return await func_to_decorate(*args, **kwargs)
        return func_to_decorate(*args, **kwargs)
    return decorated_function

