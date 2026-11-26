from common.helpers.azure_session import get_session
"""Analytics domain routes."""
import logging
from datetime import UTC, datetime, timedelta
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db

from common.helpers.responses import JSONResponse

blueprint = APIRouter()


@blueprint.get("/api/analytics/sessions/user/{user_id}")
@login_required
async def get_user_sessions_analytics(request: Request, user_id: str):
    session = get_session(request)
    try:
        from common.monitoring.usage import session_analytics
        session_analytics.mark_inactive_sessions()
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 10))
        active_only = request.query_params.get('active_only', 'false').lower() == 'true'
        raw_sessions = session_analytics.get_user_sessions(user_id=user_id, limit=limit, active_only=active_only, hours=hours)
        sessions = []
        for s in raw_sessions:
            serialized = {}
            for k, v in s.items():
                if k == 'activity_timeline':
                    continue
                elif hasattr(v, 'isoformat'):
                    serialized[k] = v.isoformat()
                else:
                    serialized[k] = v
            meta = s.get('metadata', {})
            serialized['browser'] = meta.get('browser', 'Unknown')
            serialized['os'] = meta.get('os', 'Unknown')
            serialized['device'] = meta.get('device', 'Unknown')
            sessions.append(serialized)
        analytics = session_analytics.get_session_analytics(user_id=user_id, hours=hours, active_only=active_only)
        return JSONResponse(content={"user_id": user_id, "sessions": sessions, "analytics": analytics, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting user sessions: {str(e)}")
        notify_failure("User Sessions Analytics", str(e), page="analytics", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/sessions/me")
@login_required
async def get_my_sessions_analytics(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import session_analytics
        user_id_str = str(session['user_id'])
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 20))
        active_only = request.query_params.get('active_only', 'false').lower() == 'true'
        raw_sessions = session_analytics.get_user_sessions(user_id=user_id_str, limit=limit, active_only=active_only, hours=hours)
        sessions = []
        for s in raw_sessions:
            serialized = {}
            for k, v in s.items():
                if k == 'activity_timeline':
                    continue
                elif hasattr(v, 'isoformat'):
                    serialized[k] = v.isoformat()
                else:
                    serialized[k] = v
            meta = s.get('metadata', {})
            serialized['browser'] = meta.get('browser', 'Unknown')
            serialized['os'] = meta.get('os', 'Unknown')
            serialized['device'] = meta.get('device', 'Unknown')
            sessions.append(serialized)
        analytics = session_analytics.get_session_analytics(user_id=user_id_str, hours=hours, active_only=active_only)
        return JSONResponse(content={"user_id": user_id_str, "sessions": sessions, "analytics": analytics, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting my sessions: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/sessions/all")
@login_required
async def get_all_sessions_analytics(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import session_analytics
        hours = int(request.query_params.get('hours', 24))
        analytics = session_analytics.get_session_analytics(user_id=None, hours=hours)
        return JSONResponse(content={"analytics": analytics, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting all sessions analytics: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/sessions/recent")
@login_required
async def get_recent_sessions_list(request: Request):
    session = get_session(request)
    try:
        from common.infra.mongodb_config import mongodb_manager
        from common.monitoring.usage import session_analytics
        session_analytics.mark_inactive_sessions()
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 20))
        active_only = request.query_params.get('active_only', 'false').lower() == 'true'
        time_threshold = datetime.now(UTC) - timedelta(hours=hours)
        query = {"start_time": {"$gte": time_threshold}}
        if active_only:
            query["is_active"] = True
        collection = mongodb_manager.get_collection('user_sessions')
        sessions_raw = list(collection.find(query, {"_id": 0, "activity_timeline": 0}).sort("start_time", -1).limit(limit))
        from app.models.db.user_model import User as UserModel
        unique_user_ids = set()
        for s in sessions_raw:
            uid = s.get("user_id", "")
            if uid and uid.isdigit():
                unique_user_ids.add(int(uid))
        user_map = {}
        if unique_user_ids:
            db_users = list(db.session.query(UserModel).filter(UserModel.id.in_(unique_user_ids)).all())
            for u in db_users:
                user_map[u.id] = u.username
        sessions_list = []
        for s in sessions_raw:
            uid_str = s.get("user_id", "unknown")
            if uid_str and uid_str.isdigit():
                username = user_map.get(int(uid_str), f"User {uid_str}")
            else:
                username = uid_str
            session_item = {
                "user_id": uid_str,
                "username": username,
                "session_id": s.get("session_id", ""),
                "start_time": s.get("start_time", "").isoformat() if hasattr(s.get("start_time", ""), 'isoformat') else str(s.get("start_time", "")),
                "end_time": s.get("end_time", "").isoformat() if s.get("end_time") and hasattr(s.get("end_time"), 'isoformat') else None,
                "duration_seconds": s.get("duration_seconds", 0),
                "interaction_count": s.get("interaction_count", 0),
                "is_active": s.get("is_active", False),
                "browser": s.get("metadata", {}).get("browser", "Unknown"),
                "os": s.get("metadata", {}).get("os", "Unknown"),
                "device": s.get("metadata", {}).get("device", "Unknown"),
            }
            sessions_list.append(session_item)
        return JSONResponse(content={"sessions": sessions_list, "count": len(sessions_list), "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting recent sessions list: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/sessions/activity-patterns")
@login_required
async def get_activity_patterns(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import session_analytics
        hours = int(request.query_params.get('hours', 168))
        patterns = session_analytics.get_activity_patterns(hours=hours)
        return JSONResponse(content={"patterns": patterns, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting activity patterns: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/sessions/{session_id}")
@login_required
async def get_session_details(request: Request, session_id: str):
    session = get_session(request)
    try:
        from common.monitoring.usage import session_analytics
        user_id = request.query_params.get('user_id')
        if not user_id:
            return JSONResponse({"error": "user_id parameter is required"}, status_code=400)
        session_info = session_analytics.get_session_info(user_id=user_id, session_id=session_id)
        if not session_info:
            return JSONResponse({"error": "Session not found"}, status_code=404)
        return JSONResponse(content={"session": session_info, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[SESSION_ANALYTICS] Error getting session details: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/endpoints/summary")
@login_required
async def get_endpoint_statistics_summary(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import endpoint_statistics
        hours = int(request.query_params.get('hours', 24))
        summary = endpoint_statistics.get_endpoint_summary(hours=hours)
        return JSONResponse(content={"summary": summary, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[ENDPOINT_STATS] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/endpoints/slowest")
@login_required
async def get_slowest_endpoints(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import endpoint_statistics
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 10))
        slowest = endpoint_statistics.get_slowest_endpoints(hours=hours, limit=limit)
        return JSONResponse(content={"slowest_endpoints": slowest, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[ENDPOINT_STATS] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/endpoints/errors")
@login_required
async def get_endpoint_errors(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import endpoint_statistics
        hours = int(request.query_params.get('hours', 24))
        errors = endpoint_statistics.get_error_statistics(hours=hours)
        return JSONResponse(content={"error_statistics": errors, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[ENDPOINT_STATS] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/queries/slow")
@login_required
async def get_slow_queries(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import query_performance_tracker
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 100))
        collection_name = request.query_params.get('collection')
        slow_queries = query_performance_tracker.get_slow_queries(hours=hours, limit=limit, collection_name=collection_name)
        return JSONResponse(content={"slow_queries": slow_queries, "count": len(slow_queries), "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[QUERY_PERF] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/queries/statistics")
@login_required
async def get_query_statistics(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import query_performance_tracker
        hours = int(request.query_params.get('hours', 24))
        collection_name = request.query_params.get('collection')
        stats = query_performance_tracker.get_query_statistics(hours=hours, collection_name=collection_name)
        return JSONResponse(content={"statistics": stats, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[QUERY_PERF] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/queries/by-collection")
@login_required
async def get_queries_by_collection(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import query_performance_tracker
        hours = int(request.query_params.get('hours', 24))
        by_collection = query_performance_tracker.get_queries_by_collection(hours=hours)
        return JSONResponse(content={"data": by_collection, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[QUERY_PERF] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/storage/current")
@login_required
async def get_current_storage(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import storage_metrics
        refresh = request.query_params.get('refresh', '').lower() == 'true'
        current = storage_metrics.get_current_storage(force_refresh=refresh)
        return JSONResponse(content={"storage": current, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[STORAGE] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.post("/api/analytics/storage/snapshot")
@login_required
async def capture_storage_snapshot(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import storage_metrics
        success = storage_metrics.capture_storage_snapshot()
        return JSONResponse(content={"success": success, "message": "Snapshot captured" if success else "Failed", "timestamp": datetime.now(UTC).isoformat()}, status_code=200 if success else 500)
    except Exception as e:
        logging.error(f"[STORAGE] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/storage/history")
@login_required
async def get_storage_history(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import storage_metrics
        hours = int(request.query_params.get('hours', 168))
        limit = int(request.query_params.get('limit', 100))
        history = storage_metrics.get_storage_history(hours=hours, limit=limit)
        return JSONResponse(content={"history": history, "count": len(history), "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[STORAGE] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/storage/growth")
@login_required
async def get_storage_growth(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import storage_metrics
        hours = int(request.query_params.get('hours', 168))
        growth = storage_metrics.get_storage_growth(hours=hours)
        return JSONResponse(content={"growth": growth, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[STORAGE] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/storage/breakdown")
@login_required
async def get_storage_breakdown(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import storage_metrics
        refresh = request.query_params.get('refresh', '').lower() == 'true'
        breakdown = storage_metrics.get_collection_breakdown(force_refresh=refresh)
        return JSONResponse(content={"breakdown": breakdown, "timestamp": datetime.now(UTC).isoformat()}, status_code=200)
    except Exception as e:
        logging.error(f"[STORAGE] Error: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/summary")
@login_required
async def get_user_llm_summary(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        summary = llm_usage_tracker.get_user_summary(user_id=user_id, hours=hours)
        return JSONResponse(summary, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting user summary: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/details")
@login_required
async def get_user_llm_details(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 100))
        details = llm_usage_tracker.get_user_usage(user_id=user_id, hours=hours, limit=limit)
        return JSONResponse(content={"user_id": user_id, "records": details, "count": len(details)}, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting user details: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/by-agent")
@login_required
async def get_user_llm_by_agent(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        breakdown = llm_usage_tracker.get_usage_by_agent(user_id=user_id, hours=hours)
        return JSONResponse(breakdown, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting usage by agent: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/by-feature")
@login_required
async def get_user_llm_by_feature(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        breakdown = llm_usage_tracker.get_usage_by_feature(user_id=user_id, hours=hours)
        return JSONResponse(breakdown, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting usage by feature: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/by-model")
@login_required
async def get_user_llm_by_model(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        breakdown = llm_usage_tracker.get_usage_by_model(user_id=user_id, hours=hours)
        return JSONResponse(breakdown, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting usage by model: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/user/{user_id}/trend")
@login_required
async def get_user_llm_trend(request: Request, user_id: str):
    session = get_session(request)
    try:
        current_user_id = str(session.get('user_id', ''))
        if current_user_id != str(user_id):
            from app.models.db.user_model import User
            current_user = db.session.get(User, current_user_id)
            if not current_user or current_user.role != 'admin':
                return JSONResponse({"error": "Unauthorized"}, status_code=403)
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 168))
        trend = llm_usage_tracker.get_usage_trend(user_id=user_id, hours=hours)
        return JSONResponse(trend, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting usage trend: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/all-users/summary")
@login_required
async def get_all_users_llm_summary(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        summary = llm_usage_tracker.get_all_users_summary(hours=hours)
        return JSONResponse(summary, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting all users summary: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/analytics/llm/top-consumers")
@login_required
async def get_top_llm_consumers(request: Request):
    session = get_session(request)
    try:
        from common.monitoring.usage import llm_usage_tracker
        hours = int(request.query_params.get('hours', 24))
        limit = int(request.query_params.get('limit', 10))
        top_consumers = llm_usage_tracker.get_top_consumers(hours=hours, limit=limit)
        return JSONResponse(content={"top_consumers": top_consumers, "count": len(top_consumers)}, status_code=200)
    except Exception as e:
        logging.error(f"[LLM_USAGE] Error getting top consumers: {str(e)}")
        return JSONResponse({"error": str(e)}, status_code=500)
