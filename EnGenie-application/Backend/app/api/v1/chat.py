from common.helpers.azure_session import get_session
"""Chat domain routes (Product Info)."""
import logging
import os
import uuid
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.models.db.base import db
from app.models.db.user_model import User
from common.infra.repositories.interaction_log_repository import interaction_logger

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.post("/api/chat-agent")
@login_required
async def api_chat_agent(request: Request):
    session = get_session(request)

    try:
        from domain.chat.workflows.chat_workflow import process_chat_request

        try:
            data = await request.json()
        except Exception:
            data = {}
        query = data.get("query", "").strip()

        if not query:
            return JSONResponse({"error": "Query is required"}, status_code=400)

        user_id = session.get('user_id')
        user_id_str = str(user_id) if user_id else 'anonymous'
        session_id = data.get("session_id", f"user_{user_id_str}")

        logging.info(f"[CHAT_AGENT_API] Query from user {user_id_str}: {query[:100]}...")

        from common.monitoring.benchmarking import live
        with live.capture("chat", user_input=query, user_id=user_id):
            result = process_chat_request(query, session_id, user_id)

        # Phase 1: warn-don't-raise boundary validation (payload unchanged).
        try:
            from common.models.validation import validate_response
            from domain.chat.schemas import ChatResponse
            validate_response(ChatResponse, result, context="api_chat_agent")
        except Exception:
            pass

        try:
            project_id = data.get("project_id", session_id)
            metadata = {
                "agent_type": "chat",
                "session_id": session_id,
                "project_id": project_id,
                "model": "gemini",
                "success": result.get("success", True)
            }
            interaction_logger.log_interaction(
                user_id=user_id_str,
                session_id=project_id,
                user_input=query,
                response=result.get("answer", str(result)),
                metadata=metadata,
                interaction_type="chat"
            )
        except Exception as log_error:
            logging.warning(f"[CHAT_AGENT_API] Failed to log interaction: {log_error}")

        return JSONResponse(result, status_code=200)

    except Exception as e:
        logging.exception(f"[CHAT_AGENT_API] Error processing query: {e}")

        try:
            from common.infra.repositories.notification_repository import create_failure_notification
            _uid = session.get('user_id')
            _user = db.session.get(User, _uid) if _uid else None
            create_failure_notification(
                user_id=_uid or 0,
                username=_user.username if _user else 'Unknown',
                user_email=_user.email if _user else '',
                failed_step='Chat Agent Processing',
                error_message=str(e),
                page='chat'
            )
        except Exception as notify_err:
            logging.warning(f"[NOTIFICATION] Failed to create notification: {notify_err}")

        return JSONResponse({
            "success": False,
            "error": str(e),
            "answer": "I'm sorry, I encountered an error processing your question. Please try again."
        }, status_code=500)


@blueprint.post("/api/chat/clear-session")
@login_required
async def api_chat_clear_session(request: Request):
    session = get_session(request)

    try:
        from domain.chat.agents.chat_agent import clear_pending_query

        try:
            data = await request.json()
        except Exception:
            data = {}
        user_id = str(session.get('user_id', 'anonymous'))
        session_id = data.get("session_id", f"user_{user_id}")

        clear_pending_query(session_id)

        return JSONResponse({"success": True, "message": "Session cleared"}, status_code=200)

    except Exception as e:
        logging.exception(f"[CHAT_RAG] Error clearing session: {e}")
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)
