from common.helpers.azure_session import get_session
"""Admin domain routes."""
import logging
from datetime import datetime
from fastapi import APIRouter, Request
from app.core.security import login_required
from app.core.errors import notify_failure
from app.models.db.base import db
from app.models.db.user_model import User

from common.helpers.responses import JSONResponse

blueprint = APIRouter()

@blueprint.post("/api/admin/approve_user")
@login_required
async def approve_user(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        data = {}
    user_id = data.get("user_id")
    action = data.get("action", "approve")
    user = db.session.get(User, user_id)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)
    if action == "approve":
        user.status = "active"
    elif action == "reject":
        user.status = "rejected"
    else:
        return JSONResponse({"error": "Invalid action"}, status_code=400)

    db.session.commit()
    return JSONResponse({"message": f"User {user.username} status updated to {user.status}."}, status_code=200)

@blueprint.get("/api/admin/pending_users")
@login_required
async def pending_users(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    pending = db.session.query(User).filter_by(status="pending").all()
    result = [{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name
    } for u in pending]
    return JSONResponse({"pending_users": result}, status_code=200)

@blueprint.get("/api/admin/all_users")
@login_required
async def all_users(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    users = db.session.query(User).filter(User.status != "pending").all()
    result = [{
        "id": u.id,
        "username": u.username,
        "email": u.email,
        "first_name": u.first_name,
        "last_name": u.last_name,
        "role": u.role,
        "status": u.status
    } for u in users]
    return JSONResponse({"users": result}, status_code=200)

@blueprint.post("/api/admin/update_role")
@login_required
async def update_user_role(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        data = {}
    user_id = data.get("user_id")
    new_role = data.get("role")

    if new_role not in ["user", "admin"]:
        return JSONResponse({"error": "Invalid role. Must be 'user' or 'admin'"}, status_code=400)

    user = db.session.get(User, user_id)
    if not user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    if user.id == admin_user.id:
        return JSONResponse({"error": "Cannot change your own role"}, status_code=400)

    old_role = user.role
    user.role = new_role
    db.session.commit()

    logging.info(f"Admin {admin_user.username} changed role of {user.username} from {old_role} to {new_role}")
    return JSONResponse({"message": f"User {user.username} role updated to {new_role}."}, status_code=200)


@blueprint.get("/api/admin/utilization/users")
@login_required
async def get_users_utilization(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        from common.monitoring.usage import llm_usage_tracker, session_analytics
        hours = int(request.query_params.get('hours', 24))

        users = db.session.query(User).filter(
            (User.status != "pending") | (User.status.is_(None))
        ).all()

        logging.info(f"[ADMIN] Found {len(users)} users for utilization")

        users_with_utilization = []
        for u in users:
            try:
                llm_summary = llm_usage_tracker.get_user_summary(user_id=str(u.id), hours=hours)
                session_data = session_analytics.get_session_analytics(user_id=str(u.id), hours=hours)

                users_with_utilization.append({
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "role": u.role,
                    "llm_usage": {
                        "total_requests": llm_summary.get("total_requests", 0) if llm_summary else 0,
                        "total_tokens": llm_summary.get("total_tokens", 0) if llm_summary else 0,
                        "total_cost_usd": llm_summary.get("total_cost_usd", 0) if llm_summary else 0,
                    },
                    "sessions": {
                        "total_sessions": session_data.get("total_sessions", 0) if session_data else 0,
                        "active_sessions": session_data.get("active_sessions", 0) if session_data else 0,
                        "total_interactions": session_data.get("total_interactions", 0) if session_data else 0,
                    }
                })
            except Exception as user_err:
                logging.warning(f"[ADMIN] Error getting utilization for user {u.id}: {str(user_err)}")
                users_with_utilization.append({
                    "id": u.id,
                    "username": u.username,
                    "email": u.email,
                    "first_name": u.first_name,
                    "last_name": u.last_name,
                    "role": u.role,
                    "llm_usage": {"total_requests": 0, "total_tokens": 0, "total_cost_usd": 0},
                    "sessions": {"total_sessions": 0, "active_sessions": 0, "total_interactions": 0}
                })

        users_with_utilization.sort(key=lambda x: x["llm_usage"]["total_tokens"], reverse=True)

        logging.info(f"[ADMIN] Returning {len(users_with_utilization)} users with utilization data")
        return JSONResponse({
            "users": users_with_utilization,
            "time_period_hours": hours,
            "count": len(users_with_utilization)
        }, status_code=200)

    except Exception as e:
        logging.error(f"[ADMIN] Error getting users utilization: {str(e)}", exc_info=True)
        notify_failure("Admin Users Utilization Fetch", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/admin/utilization/user/{user_id}")
@login_required
async def get_user_utilization_detail(request: Request, user_id: str):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    target_user = db.session.get(User, user_id)
    if not target_user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    try:
        from common.monitoring.usage import llm_usage_tracker, session_analytics
        hours = int(request.query_params.get('hours', 24))
        user_id_str = str(user_id)

        llm_summary = llm_usage_tracker.get_user_summary(user_id=user_id_str, hours=hours)
        llm_by_agent = llm_usage_tracker.get_usage_by_agent(user_id=user_id_str, hours=hours)
        llm_by_feature = llm_usage_tracker.get_usage_by_feature(user_id=user_id_str, hours=hours)
        llm_by_model = llm_usage_tracker.get_usage_by_model(user_id=user_id_str, hours=hours)
        llm_trend = llm_usage_tracker.get_usage_trend(user_id=user_id_str, hours=hours)

        session_data = session_analytics.get_session_analytics(user_id=user_id_str, hours=hours)
        recent_sessions = session_analytics.get_user_sessions(user_id=user_id_str, limit=10)

        return JSONResponse({
            "user": {
                "id": target_user.id,
                "username": target_user.username,
                "email": target_user.email,
                "first_name": target_user.first_name,
                "last_name": target_user.last_name,
                "role": target_user.role
            },
            "time_period_hours": hours,
            "llm_usage": {
                "summary": llm_summary,
                "by_agent": llm_by_agent.get("by_agent", []),
                "by_feature": llm_by_feature.get("by_feature", []),
                "by_model": llm_by_model.get("by_model", []),
                "trend": llm_trend.get("trend_data", [])
            },
            "sessions": {
                "analytics": session_data,
                "recent": [
                    {
                        k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                        for k, v in s.items()
                        if k != 'activity_timeline'
                    }
                    for s in (recent_sessions or [])
                ]
            }
        }, status_code=200)

    except Exception as e:
        logging.error(f"[ADMIN] Error getting user utilization detail: {str(e)}")
        notify_failure("Admin User Utilization Detail Fetch", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.get("/api/utilization/me")
@login_required
async def get_my_utilization(request: Request):
    session = get_session(request)

    current_user = db.session.get(User, session['user_id'])
    if not current_user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    try:
        from common.monitoring.usage import llm_usage_tracker, session_analytics
        hours = int(request.query_params.get('hours', 24))
        user_id_str = str(current_user.id)

        llm_summary = llm_usage_tracker.get_user_summary(user_id=user_id_str, hours=hours)
        llm_by_agent = llm_usage_tracker.get_usage_by_agent(user_id=user_id_str, hours=hours)
        llm_by_feature = llm_usage_tracker.get_usage_by_feature(user_id=user_id_str, hours=hours)
        llm_by_model = llm_usage_tracker.get_usage_by_model(user_id=user_id_str, hours=hours)
        llm_trend = llm_usage_tracker.get_usage_trend(user_id=user_id_str, hours=hours)

        session_data = session_analytics.get_session_analytics(user_id=user_id_str, hours=hours)
        recent_sessions = session_analytics.get_user_sessions(user_id=user_id_str, limit=10)

        return JSONResponse({
            "user": {
                "id": current_user.id,
                "username": current_user.username,
                "email": current_user.email,
                "first_name": current_user.first_name,
                "last_name": current_user.last_name,
                "role": current_user.role
            },
            "time_period_hours": hours,
            "llm_usage": {
                "summary": llm_summary,
                "by_agent": llm_by_agent.get("by_agent", []),
                "by_feature": llm_by_feature.get("by_feature", []),
                "by_model": llm_by_model.get("by_model", []),
                "trend": llm_trend.get("trend_data", [])
            },
            "sessions": {
                "analytics": session_data,
                "recent": [
                    {
                        k: (v.isoformat() if hasattr(v, 'isoformat') else v)
                        for k, v in s.items()
                        if k != 'activity_timeline'
                    }
                    for s in (recent_sessions or [])
                ]
            }
        }, status_code=200)

    except Exception as e:
        logging.error(f"Error getting my utilization: {str(e)}")
        notify_failure("My Utilization Fetch", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"error": str(e)}, status_code=500)


@blueprint.post("/api/admin/backfill_fields")
@login_required
async def backfill_fields(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        apply = bool(data.get("apply", False))

        from app.services.migration_service import run_field_backfill
        result = run_field_backfill(apply=apply)
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except Exception as e:
        logging.error(f"Error executing fields backfill: {str(e)}")
        notify_failure("Admin Backfill Execute", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/admin/migrate_restructured_db")
@login_required
async def migrate_restructured_db(request: Request):
    """Migrate the Restructured DB to the new SchemaSpec shape.

    Body: {"apply": true}   — actually write changes (default: dry-run).

    Converts every L0/L1/L2 node's `specifications` to
      {id, safety:[SpecParameter], electrical, mechanical, process,
       environmental, performance, certifications, other}
    and normalises L3/L4 `device` blocks to
      {id, oem, model_series, model_number, specs_doc_id, spec_doc_url, parent_id, key}.
    The migration is idempotent: re-running on an already-migrated DB is a no-op.
    """
    session = get_session(request)
    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        try:
            data = await request.json()
        except Exception:
            data = {}
        apply = bool(data.get("apply", False))

        from app.services.restructured_migration_service import run_restructured_migration
        result = run_restructured_migration(apply=apply)
        result["success"] = result.get("errors", 0) == 0
        return JSONResponse(result, status_code=200)
    except Exception as e:
        logging.error(f"[ADMIN] Restructured DB migration failed: {e}", exc_info=True)
        notify_failure("Restructured DB Migration", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@blueprint.post("/api/admin/sync_hub_prompts")
@login_required
async def sync_hub_prompts(request: Request):
    session = get_session(request)

    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        from common.ai.prompts.hub_syncer import sync_prompts_to_hub
        result = sync_prompts_to_hub()
        return JSONResponse(result, status_code=200 if result.get("success") else 500)
    except Exception as e:
        logging.error(f"Error executing prompt sync to Hub: {str(e)}")
        notify_failure("Admin Prompt Sync Execute", str(e), page="admin", user_id=session.get('user_id'))
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)




# ── Advanced specifications generation (admin) ────────────────────────────────
@blueprint.post("/api/admin/advanced-specs/generate")
@login_required
async def advanced_specs_generate(request: Request):
    """Generate advanced specifications (LLM = configured provider, e.g. Kimi).

    Body: {product_type?: str, dry_run?: bool, limit?: int, workers?: int}
    Runs in a background thread; poll /api/admin/advanced-specs/status.
    """
    session = get_session(request)
    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    from domain.search.services import advanced_specs_service
    if advanced_specs_service.get_status().get("running"):
        return JSONResponse({"error": "A generation run is already in progress"}, status_code=409)

    try:
        data = await request.json()
    except Exception:
        data = {}

    import threading
    kwargs = {
        "product_type": data.get("product_type"),
        "dry_run": bool(data.get("dry_run", False)),
        "limit": int(data["limit"]) if data.get("limit") else None,
        "workers": int(data.get("workers", 5)),
    }

    def _worker():
        try:
            advanced_specs_service.run_generation(**kwargs)
        except Exception as e:
            logging.error(f"[ADMIN] advanced specs generation crashed: {e}")

    threading.Thread(target=_worker, daemon=True, name="advanced-specs-gen").start()
    return JSONResponse({"started": True, **kwargs}, status_code=202)


@blueprint.get("/api/admin/advanced-specs/status")
@login_required
async def advanced_specs_status(request: Request):
    """Current/last advanced-specs generation progress."""
    session = get_session(request)
    admin_user = db.session.get(User, session['user_id'])
    if admin_user.role != "admin":
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    from domain.search.services import advanced_specs_service
    return JSONResponse(advanced_specs_service.get_status())
