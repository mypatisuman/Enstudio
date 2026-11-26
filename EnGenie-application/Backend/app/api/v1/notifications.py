from common.helpers.azure_session import get_session
"""Notifications domain routes."""
import logging
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db
from app.models.db.user_model import User

from common.helpers.responses import JSONResponse

blueprint = APIRouter()

@blueprint.get("/api/notifications")
@login_required
async def api_get_notifications(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        from common.infra.repositories.notification_repository import get_admin_notifications

        limit = int(request.query_params.get("limit", 50))
        skip = int(request.query_params.get("skip", 0))
        filter_type = request.query_params.get("filter", "all")

        result = get_admin_notifications(limit=limit, skip=skip, filter_type=filter_type)
        return JSONResponse(result, status_code=200)

    except Exception as e:
        logging.exception("Failed to fetch notifications")
        notify_failure("Notifications Fetch", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/notifications/unread-count")
@login_required
async def api_notifications_unread_count(request: Request):
    session = get_session(request)

    try:
        user_role = session.get('user_role')
        if user_role != 'admin':
            return JSONResponse({"unread_count": 0}, status_code=200)

        from common.infra.repositories.notification_repository import get_unread_count
        count = get_unread_count()
        return JSONResponse({"unread_count": count}, status_code=200)

    except Exception as e:
        logging.error(f"Failed to get unread notification count: {e}")
        notify_failure("Notifications Unread Count", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"unread_count": 0}, status_code=200)


@blueprint.post("/api/notifications/{notification_id}/read")
@login_required
async def api_mark_notification_read(request: Request, notification_id: str):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        from common.infra.repositories.notification_repository import mark_notification_read
        success = mark_notification_read(notification_id)

        if success:
            return JSONResponse({"success": True, "message": "Notification marked as read"}, status_code=200)
        else:
            return JSONResponse({"error": "Notification not found or already read"}, status_code=404)

    except Exception as e:
        logging.exception("Failed to mark notification as read")
        notify_failure("Mark Notification as Read", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.post("/api/notifications/mark-all-read")
@login_required
async def api_mark_all_notifications_read(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        from common.infra.repositories.notification_repository import mark_all_notifications_read
        count = mark_all_notifications_read()
        return JSONResponse({"success": True, "marked_count": count}, status_code=200)

    except Exception as e:
        logging.exception("Failed to mark all notifications as read")
        notify_failure("Mark All Notifications as Read", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)

@blueprint.delete("/api/notifications/{notification_id}")
@login_required
async def api_delete_notification(request: Request, notification_id: str):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        from common.infra.repositories.notification_repository import delete_admin_notification
        success = delete_admin_notification(notification_id)

        if success:
            return JSONResponse({"success": True, "message": "Notification deleted"}, status_code=200)
        else:
            return JSONResponse({"error": "Notification not found or could not be deleted"}, status_code=404)

    except Exception as e:
        logging.exception("Failed to delete notification")
        notify_failure("Delete Notification", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)

@blueprint.delete("/api/notifications")
@login_required
async def api_delete_all_notifications(request: Request):
    session = get_session(request)

    try:
        user_id = session.get('user_id')
        user = db.session.get(User, user_id)
        if not user or user.role != 'admin':
            return JSONResponse({"error": "Admin access required"}, status_code=403)

        from common.infra.repositories.notification_repository import delete_all_notifications
        count = delete_all_notifications()
        return JSONResponse({"success": True, "deleted_count": count}, status_code=200)

    except Exception as e:
        logging.exception("Failed to delete all notifications")
        notify_failure("Delete All Notifications", str(e), page="notifications", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)
