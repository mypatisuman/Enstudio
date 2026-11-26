"""
Centralized Notification Helpers
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)

def notify_failure(failed_step: str, error_message: str, state: dict | None = None, page: str = "general", **extra_context: Any):
    """
    Send a failure notification centrally. Silently swallows errors.
    
    Args:
        state: The agentic state dict (if available) to extract user info. Can be None.
        failed_step: The name of the process that failed.
        error_message: The exception message or error description.
        page: The domain/page context (e.g., 'search', 'solution', 'chat').
        extra_context: Additional key-value pairs for metadata.
    """
    try:
        from app.models.db.base import db
        from app.models.db.user_model import User
        from common.infra.repositories.notification_repository import create_failure_notification
        
        user_id = 0
        username = "Unknown"
        user_email = ""
        
        # Try to extract user info from state if provided
        if state:
            user_id = state.get("user_id") or 0
            username = state.get("username", "Unknown")
            user_email = state.get("user_email", "")
        else:
            # Fallback for headless services not passing state
            _uid = None
            if _uid:
                try:
                    _user = db.session.get(User, _uid)
                    if _user:
                        username = _user.username
                        user_email = _user.email
                        user_id = _uid
                except:
                    pass

        create_failure_notification(
            user_id=user_id,
            username=username,
            user_email=user_email,
            failed_step=failed_step,
            error_message=error_message,
            page=page,
            additional_context=extra_context,
        )
    except Exception as notify_err:
        logger.warning(f"[NOTIFICATION] Failed to create {failed_step} notification: {notify_err}")


def notify_task_completion(
    title: str,
    message: str,
    user_id: int | str | None = None,
    page: str = "general",
    task_type: str = "analysis",
    stream_id: str | None = None,
    target_url: str | None = None,
    **extra_context: Any
):
    """
    Send a background task completion notification centrally.
    """
    try:
        from app.models.db.base import db
        from app.models.db.user_model import User
        from common.infra.repositories.notification_repository import create_task_completion_notification

        uid = int(user_id) if user_id and str(user_id).isdigit() else 0
        username = "User"
        user_email = ""

        if uid > 0:
            try:
                _user = db.session.get(User, uid)
                if _user:
                    username = _user.username
                    user_email = _user.email
            except Exception:
                pass

        return create_task_completion_notification(
            user_id=uid,
            username=username,
            user_email=user_email,
            title=title,
            message=message,
            page=page,
            task_type=task_type,
            stream_id=stream_id,
            target_url=target_url,
            additional_context=extra_context,
        )
    except Exception as notify_err:
        logger.warning(f"[NOTIFICATION] Failed to create task completion notification '{title}': {notify_err}")
        return None

