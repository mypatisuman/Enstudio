"""
Notification service layer — app-level orchestration for admin notifications.

Delegates to common/repositories/notification_repository.py.
Route handlers import from here to stay thin HTTP-only layers.
"""
from common.infra.repositories.notification_repository import create_failure_notification


def notify_failure(
    user_id: int,
    username: str,
    user_email: str,
    failed_step: str,
    error_message: str,
    page: str = "search",
    **additional_context,
) -> None:
    """Create an admin failure notification. Silently swallows all errors."""
    try:
        create_failure_notification(
            user_id=user_id,
            username=username,
            user_email=user_email,
            failed_step=failed_step,
            error_message=error_message,
            page=page,
            additional_context=additional_context,
        )
    except Exception:
        pass
