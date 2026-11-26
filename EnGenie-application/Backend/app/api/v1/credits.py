"""
Credits domain routes.

Endpoints:
  GET  /api/credits/balance                 — current user's balance, lifetime totals, costs, enforcement flag
  GET  /api/credits/history                 — current user's transaction ledger (paginated)
  POST /api/admin/credits/topup             — admin: grant (or deduct) credits for a user
  GET  /api/admin/credits/accounts          — admin: list all credit accounts
  GET  /api/admin/credits/history/{user_id} — admin: a specific user's ledger
"""
import logging

from fastapi import APIRouter, Request

from app.core.security import login_required
from app.models.db.base import db
from app.models.db.user_model import User
from common.helpers.azure_session import get_session
from common.helpers.responses import JSONResponse
from common.services import credit_service

blueprint = APIRouter()

MAX_PAGE_SIZE = 200


def _page_params(request: Request):
    try:
        limit = min(int(request.query_params.get("limit", 50)), MAX_PAGE_SIZE)
        skip = max(int(request.query_params.get("skip", 0)), 0)
    except (TypeError, ValueError):
        limit, skip = 50, 0
    return max(limit, 1), skip


def _require_admin(session):
    """Return the admin User or None (mirrors the admin.py gate)."""
    admin_user = db.session.get(User, session.get('user_id'))
    if not admin_user or admin_user.role != "admin":
        return None
    return admin_user


@blueprint.get("/api/credits/balance")
@login_required
async def credits_balance(request: Request):
    session = get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        return JSONResponse({"error": "No user in session"}, status_code=401)
    return JSONResponse({"success": True, **credit_service.get_balance_summary(user_id)}, status_code=200)


@blueprint.get("/api/credits/history")
@login_required
async def credits_history(request: Request):
    session = get_session(request)
    user_id = session.get('user_id')
    if not user_id:
        return JSONResponse({"error": "No user in session"}, status_code=401)
    limit, skip = _page_params(request)
    transactions = credit_service.get_history(user_id, limit=limit, skip=skip)
    return JSONResponse({
        "success": True,
        "transactions": transactions,
        "limit": limit,
        "skip": skip,
    }, status_code=200)


@blueprint.post("/api/admin/credits/topup")
@login_required
async def admin_credits_topup(request: Request):
    session = get_session(request)
    admin_user = _require_admin(session)
    if not admin_user:
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)

    try:
        data = await request.json()
    except Exception:
        data = {}

    target_user_id = data.get("user_id")
    amount = data.get("amount")
    note = data.get("note", "")

    if not target_user_id:
        return JSONResponse({"error": "user_id is required"}, status_code=400)
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return JSONResponse({"error": "amount must be an integer"}, status_code=400)
    if amount == 0:
        return JSONResponse({"error": "amount must be non-zero"}, status_code=400)

    target_user = db.session.get(User, target_user_id)
    if not target_user:
        return JSONResponse({"error": "User not found"}, status_code=404)

    new_balance = credit_service.admin_adjust(
        user_id=target_user_id,
        amount=amount,
        performed_by=session.get('user_id'),
        note=note,
    )
    if new_balance is None:
        return JSONResponse({"error": "Failed to apply credit adjustment"}, status_code=500)

    logging.info(
        f"[CREDITS] Admin {session.get('user_id')} adjusted user {target_user_id} "
        f"by {amount} credits (new balance: {new_balance})"
    )
    return JSONResponse({
        "success": True,
        "user_id": str(target_user_id),
        "amount": amount,
        "balance": new_balance,
    }, status_code=200)


@blueprint.get("/api/admin/credits/accounts")
@login_required
async def admin_credits_accounts(request: Request):
    session = get_session(request)
    if not _require_admin(session):
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)
    limit, skip = _page_params(request)
    from common.infra.repositories.credit_repository import credit_repository
    accounts = credit_repository.list_accounts(limit=limit, skip=skip)
    return JSONResponse({
        "success": True,
        "accounts": accounts,
        "limit": limit,
        "skip": skip,
        "enforcement_enabled": credit_service.CREDITS_ENFORCEMENT_ENABLED,
        "workflow_costs": dict(credit_service.WORKFLOW_COSTS),
    }, status_code=200)


@blueprint.get("/api/admin/credits/history/{user_id}")
@login_required
async def admin_credits_history(request: Request, user_id: str):
    session = get_session(request)
    if not _require_admin(session):
        return JSONResponse({"error": "Forbidden: Admins only"}, status_code=403)
    limit, skip = _page_params(request)
    transactions = credit_service.get_history(user_id, limit=limit, skip=skip)
    return JSONResponse({
        "success": True,
        "user_id": str(user_id),
        "transactions": transactions,
        "limit": limit,
        "skip": skip,
    }, status_code=200)
