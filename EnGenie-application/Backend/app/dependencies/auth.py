"""
Authentication Dependencies
"""
import logging

from app.core.security import validate_jwt_token

logger = logging.getLogger(__name__)

def get_current_user(request) -> dict:
    """
    Extracts and validates JWT Bearer token from request headers.
    Returns user dict with 'valid', 'user_id', etc.
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        validation = validate_jwt_token(token)
        if validation["valid"]:
            return validation
        logger.warning(f"[AUTH] JWT invalid: {validation.get('error')}")

    # Fallback: check session from cookie or x-session-id
    try:
        from common.helpers.azure_session import get_session
        session = get_session(request)
        if session and session.get("user_id"):
            return {
                "valid": True,
                "user_id": session.get("user_id"),
                "username": session.get("username", "user"),
            }
    except Exception:
        pass

    logger.warning("[AUTH] Unauthorized — 401")
    return {"valid": False, "error": "Unauthorized: Please log in"}

def require_admin(request) -> dict:
    """
    Raises/returns error if they are not an admin.
    """
    user = get_current_user(request)
    if not user.get("valid"):
        return user
        
    from app.models.db.user_model import User
    from app.core.database import db_session
    
    user_id = user.get("user_id")
    with db_session() as session:
        db_user = session.query(User).get(user_id)
        if not db_user or db_user.role != 'admin':
            logger.warning(f"[AUTH] User {user_id} attempted to access admin route")
            return {"valid": False, "error": "Forbidden: Admin access required"}
        
    return user
