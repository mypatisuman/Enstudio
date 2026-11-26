"""
Notification Manager for Admin Notifications
Handles creating, fetching, and managing notifications when users fail at steps.
Notifications are stored in MongoDB and visible to admin users.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from bson import ObjectId

from common.infra.mongodb_config import mongodb_manager

logger = logging.getLogger(__name__)

# Collection name
NOTIFICATIONS_COLLECTION = "notifications"

# In-memory cache for unread count (polled every 5s by frontend)
_unread_count_cache: dict = {"count": 0, "expires_at": 0.0}
_UNREAD_COUNT_CACHE_TTL = 15  # seconds


def _get_collection():
    """Get the notifications collection from MongoDB"""
    return mongodb_manager.get_collection(NOTIFICATIONS_COLLECTION)


def _safe_create_index(collection, keys, **kwargs):
    """Safely create an index, handling CosmosDB conflicts gracefully."""
    try:
        collection.create_index(keys, **kwargs)
    except Exception as e:
        error_str = str(e)
        if "IndexKeySpecsConflict" in error_str or "code': 86" in error_str or "same name as the requested index" in error_str:
            logger.debug("Index already exists (CosmosDB conflict), skipping")
        else:
            raise


def _ensure_indexes():
    """Create indexes for efficient notification queries"""
    try:
        collection = _get_collection()
        # Index for fetching notifications by admin (unread first, newest first)
        collection.create_index([
            ("is_read", 1),
            ("created_at", -1)
        ])
        # Index for fetching by user
        collection.create_index([
            ("user_id", 1),
            ("created_at", -1)
        ])
        # TTL index - auto-delete notifications after 90 days
        _safe_create_index(
            collection,
            "created_at",
            expireAfterSeconds=60 * 60 * 24 * 90
        )
        logger.info("Notification indexes created successfully")
    except Exception as e:
        logger.warning(f"Could not create notification indexes: {e}")


# Initialize indexes on import
try:
    _ensure_indexes()
except Exception as e:
    # P1.13: Log error instead of silently swallowing - TTL index is critical
    logger.error(f"[NOTIFICATION] Failed to create notification indexes: {e}. "
                 "Notifications will accumulate indefinitely without TTL index.")


def create_failure_notification(
    user_id: int,
    username: str,
    user_email: str,
    failed_step: str,
    error_message: str,
    page: str = "unknown",
    additional_context: dict[str, Any] | None = None
) -> str | None:
    """
    Create a notification when a user fails at a step.

    Args:
        user_id: The numeric ID of the user who failed
        username: The username of the user
        user_email: The email of the user
        failed_step: The step/operation that failed (e.g., "Analysis", "Search", "Solution")
        error_message: Human-readable error description
        page: Which page the failure occurred on (search, solution, chat)
        additional_context: Optional extra context about the failure

    Returns:
        The notification ID if created successfully, None otherwise
    """
    try:
        collection = _get_collection()

        notification = {
            "user_id": user_id,
            "username": username,
            "user_email": user_email,
            "failed_step": failed_step,
            "error_message": error_message,
            "page": page,
            "is_read": False,
            "created_at": datetime.now(UTC),
            "additional_context": additional_context or {}
        }

        result = collection.insert_one(notification)
        notification_id = str(result.inserted_id)

        logger.info(
            f"[NOTIFICATION] Created failure notification: "
            f"user={username} (ID:{user_id}), step={failed_step}, page={page}"
        )

        return notification_id

    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to create notification: {e}")
        return None


def create_task_completion_notification(
    user_id: int,
    username: str,
    user_email: str,
    title: str,
    message: str,
    page: str = "general",
    task_type: str = "analysis",
    stream_id: str | None = None,
    target_url: str | None = None,
    additional_context: dict[str, Any] | None = None
) -> str | None:
    """
    Create a success/completion notification when a long-running background task finishes.
    """
    try:
        collection = _get_collection()

        notification = {
            "user_id": user_id,
            "username": username,
            "user_email": user_email,
            "type": "task_complete",
            "title": title,
            "message": message,
            "failed_step": title,  # For backward-compatible UI schemas
            "error_message": message,
            "status": "success",
            "page": page,
            "task_type": task_type,
            "stream_id": stream_id,
            "target_url": target_url,
            "play_sound": True,
            "is_read": False,
            "created_at": datetime.now(UTC),
            "additional_context": additional_context or {}
        }

        result = collection.insert_one(notification)
        notification_id = str(result.inserted_id)

        logger.info(
            f"[NOTIFICATION] Created task completion notification: "
            f"user={username} (ID:{user_id}), title={title}, page={page}"
        )

        return notification_id

    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to create completion notification: {e}")
        return None



def get_admin_notifications(
    limit: int = 50,
    skip: int = 0,
    filter_type: str = "all"
) -> dict[str, Any]:
    """
    Get notifications for admin users.

    Args:
        limit: Maximum number of notifications to return
        skip: Number to skip (for pagination)
        filter_type: "all", "unread", or "read"

    Returns:
        Dict with notifications list and counts
    """
    try:
        collection = _get_collection()

        # Build query
        query = {}
        if filter_type == "unread":
            query["is_read"] = False
        elif filter_type == "read":
            query["is_read"] = True

        # Get total and unread counts
        total_count = collection.count_documents({})
        unread_count = collection.count_documents({"is_read": False})

        # Fetch notifications (newest first)
        cursor = collection.find(query).sort("created_at", -1).skip(skip).limit(limit)

        # Phase 2: validate-on-read via NotificationDoc; output shape preserved exactly.
        from common.models.documents import NotificationDoc
        notifications = [NotificationDoc.from_mongo(doc).to_api_dict() for doc in cursor]

        return {
            "notifications": notifications,
            "total_count": total_count,
            "unread_count": unread_count
        }

    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to fetch notifications: {e}")
        return {
            "notifications": [],
            "total_count": 0,
            "unread_count": 0
        }


def mark_notification_read(notification_id: str) -> bool:
    """Mark a single notification as read"""
    try:
        collection = _get_collection()
        result = collection.update_one(
            {"_id": ObjectId(notification_id)},
            {"$set": {"is_read": True}}
        )
        return result.modified_count > 0
    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to mark notification as read: {e}")
        return False


def mark_all_notifications_read() -> int:
    """Mark all notifications as read. Returns count of updated notifications."""
    try:
        collection = _get_collection()
        result = collection.update_many(
            {"is_read": False},
            {"$set": {"is_read": True}}
        )
        return result.modified_count
    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to mark all notifications as read: {e}")
        return 0


def get_unread_count() -> int:
    """Get the count of unread notifications (cached for 15s to avoid polling overhead)"""
    import time as _time
    now = _time.time()
    if now < _unread_count_cache["expires_at"]:
        return _unread_count_cache["count"]
    try:
        collection = _get_collection()
        count = collection.count_documents({"is_read": False}, maxTimeMS=5000)
        _unread_count_cache["count"] = count
        _unread_count_cache["expires_at"] = now + _UNREAD_COUNT_CACHE_TTL
        return count
    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to get unread count: {e}")
        return 0

def delete_admin_notification(notification_id: str) -> bool:
    """Delete a single notification from the database"""
    try:
        collection = _get_collection()
        result = collection.delete_one({"_id": ObjectId(notification_id)})
        return result.deleted_count > 0
    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to delete notification: {e}")
        return False

def delete_all_notifications() -> int:
    """Delete all notifications from the database. Returns count of deleted notifications."""
    try:
        collection = _get_collection()
        result = collection.delete_many({})
        return result.deleted_count
    except Exception as e:
        logger.error(f"[NOTIFICATION] Failed to delete all notifications: {e}")
        return 0
