"""Structured error codes, helpers, and exception handler registration."""
import logging
import uuid


# ── Error code taxonomy ────────────────────────────────────────────────────

class ErrorCode:
    # LLM / AI
    LLM_RATE_LIMITED     = "LLM_RATE_LIMITED"
    LLM_PROVIDER_DOWN    = "LLM_PROVIDER_DOWN"
    LLM_TIMEOUT          = "LLM_TIMEOUT"
    LLM_INVALID_RESPONSE = "LLM_INVALID_RESPONSE"
    # RAG / documents
    RAG_TIMEOUT          = "RAG_TIMEOUT"
    RAG_PARSE_FAILED     = "RAG_PARSE_FAILED"
    BLOB_UNAVAILABLE     = "BLOB_UNAVAILABLE"
    # Database
    DB_UNAVAILABLE       = "DB_UNAVAILABLE"
    DB_TIMEOUT           = "DB_TIMEOUT"
    # Memory
    MEMORY_OVERFLOW      = "MEMORY_OVERFLOW"
    SESSION_NOT_FOUND    = "SESSION_NOT_FOUND"
    # Auth / access
    AUTH_REQUIRED        = "AUTH_REQUIRED"
    PERMISSION_DENIED    = "PERMISSION_DENIED"
    # Input
    INVALID_INPUT        = "INVALID_INPUT"
    FILE_TOO_LARGE       = "FILE_TOO_LARGE"
    UNSUPPORTED_FORMAT   = "UNSUPPORTED_FORMAT"
    # Generic
    INTERNAL_ERROR       = "INTERNAL_ERROR"


def _classify_error_code(error: Exception) -> str:
    """Infer a structured error code from the exception type and message."""
    error_str = str(error).lower()
    error_type = type(error).__name__

    if any(x in error_str for x in ("429", "rate limit", "quota exceeded",
                                     "resource_exhausted", "too many requests")):
        return ErrorCode.LLM_RATE_LIMITED

    if any(x in error_str for x in ("timeout", "timed out", "deadline exceeded")):
        if any(x in error_str for x in ("llm", "gemini", "openai", "anthropic", "grok")):
            return ErrorCode.LLM_TIMEOUT
        if any(x in error_str for x in ("rag", "blob", "azure")):
            return ErrorCode.RAG_TIMEOUT
        if any(x in error_str for x in ("mongo", "database", "db")):
            return ErrorCode.DB_TIMEOUT
        return ErrorCode.LLM_TIMEOUT

    if any(x in error_str for x in ("connection refused", "service unavailable",
                                     "unreachable", "network", "connect")):
        if any(x in error_str for x in ("mongo", "database")):
            return ErrorCode.DB_UNAVAILABLE
        if any(x in error_str for x in ("blob", "azure", "storage")):
            return ErrorCode.BLOB_UNAVAILABLE
        return ErrorCode.LLM_PROVIDER_DOWN

    if "jsondecode" in error_type.lower() or "json" in error_str:
        return ErrorCode.LLM_INVALID_RESPONSE

    if any(x in error_str for x in ("pymongo", "mongo", "operationerror")):
        return ErrorCode.DB_UNAVAILABLE

    return ErrorCode.INTERNAL_ERROR


def _create_error_response(
    error: Exception,
    status_code: int = 500,
    context: str = "",
    error_code: str | None = None,
):
    """Create a secure error response that doesn't leak internal details."""
    import json
    from common.helpers.responses import JSONResponse
    error_id = str(uuid.uuid4())[:8]
    code = error_code or _classify_error_code(error)

    logging.error(
        f"[ERROR:{error_id}] [{code}] {context} - "
        f"{type(error).__name__}: {error}",
        exc_info=True,
    )

    return JSONResponse(
        {
            "success":    False,
            "error":      "An error occurred while processing your request.",
            "error_code": code,
            "error_id":   error_id,
        },
        status_code=status_code
    )



# ── Failure notification helper ────────────────────────────────────────────

def notify_failure(
    failed_step: str,
    error_message: str,
    page: str = "search",
    user_id: int | None = None,
    **extra_context,
) -> None:
    """Send an admin failure notification.  Silently swallows all errors.

    Args:
        failed_step:   Short label of the step that failed (e.g. "Solution Agent Processing").
        error_message: Exception message string.
        page:          Page context for the notification ("search", "solution", etc.).
        user_id:       Optional integer user ID.  Resolved to a User object when possible.
        **extra_context: Any additional key-value pairs to attach to the notification.
    """
    try:
        from app.models.db.base import db
        from app.models.db.user_model import User
        from common.infra.repositories.notification_repository import create_failure_notification

        _uid = user_id if user_id is not None else 0
        _user = None
        try:
            if _uid:
                _user = db.session.get(User, _uid)
        except Exception:
            pass

        create_failure_notification(
            user_id=_uid or 0,
            username=_user.username if _user else "Unknown",
            user_email=_user.email if _user else "",
            failed_step=failed_step,
            error_message=error_message,
            page=page,
            additional_context=extra_context,
        )
    except Exception as _err:
        logging.warning(f"[NOTIFICATION] Failed to create {failed_step} notification: {_err}")
