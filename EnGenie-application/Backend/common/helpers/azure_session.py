import os
import json
import logging
import redis

# TTL for sessions in Redis
SESSION_TTL = 86400  # 24 hours

_redis_available = None
_sessions_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".sessions")

def get_redis_client():
    return redis.from_url(
        os.getenv("REDIS_URL", "redis://localhost:6379/0"),
        decode_responses=True,
        socket_connect_timeout=2  # Fail faster for local development/unreachable Redis
    )

def check_redis_availability():
    global _redis_available
    if _redis_available is not None:
        return _redis_available
    
    redis_url = os.getenv("REDIS_URL")
    if not redis_url:
        logging.warning("[AzureSession] REDIS_URL not set. Using filesystem sessions.")
        _redis_available = False
        return False
        
    try:
        # Quick ping to check if Redis is reachable
        client = get_redis_client()
        client.ping()
        _redis_available = True
        logging.info("[AzureSession] Successfully connected to Redis.")
    except Exception as e:
        logging.warning(f"[AzureSession] Redis connection failed ({e}). Falling back to filesystem sessions.")
        _redis_available = False
        
    return _redis_available

class AzureSession:
    """
    A dict-like wrapper around Redis to mimic request.session.
    Needs an explicit session identifier (like user_id or search_session_id or an explicit cookie).
    Since we migrated away from Azure Functions, the client must pass an x-session-id header.
    Falls back to a local filesystem storage under .sessions/ if Redis is unreachable.
    """
    def __init__(self, session_id: str):
        self.session_id = session_id or "default_session"
        self._key = f"azure_session:{self.session_id}"
        self._redis_available = check_redis_availability()
        if self._redis_available:
            self._client = get_redis_client()
        self._data = self._load()

    def _get_fallback_filepath(self):
        os.makedirs(_sessions_dir, exist_ok=True)
        # Sanitize session_id to prevent directory traversal
        safe_session_id = "".join(c for c in self.session_id if c.isalnum() or c in ("-", "_"))
        return os.path.join(_sessions_dir, f"session_{safe_session_id}.json")

    def _load(self):
        if self._redis_available:
            try:
                raw = self._client.get(self._key)
                return json.loads(raw) if raw else {}
            except Exception as e:
                logging.error(f"[AzureSession] load error: {e}")
                return {}
        else:
            filepath = self._get_fallback_filepath()
            if os.path.exists(filepath):
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        return json.load(f)
                except Exception as e:
                    logging.error(f"[AzureSession] filesystem load error: {e}")
            return {}

    def save(self):
        if self._redis_available:
            try:
                self._client.set(self._key, json.dumps(self._data), ex=SESSION_TTL)
            except Exception as e:
                logging.error(f"[AzureSession] save error: {e}")
        else:
            filepath = self._get_fallback_filepath()
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(self._data, f)
            except Exception as e:
                logging.error(f"[AzureSession] filesystem save error: {e}")


    def get(self, key, default=None):
        return self._data.get(key, default)

    def __setitem__(self, key, value):
        self._data[key] = value
        self.save()

    def __getitem__(self, key):
        return self._data[key]

    def __contains__(self, key):
        return key in self._data

    def pop(self, key, default=None):
        val = self._data.pop(key, default)
        self.save()
        return val

    def clear(self):
        self._data = {}
        if self._redis_available:
            try:
                self._client.delete(self._key)
            except:
                pass
        else:
            filepath = self._get_fallback_filepath()
            if os.path.exists(filepath):
                try:
                    os.remove(filepath)
                except:
                    pass


def get_session(req) -> AzureSession:
    """
    Given a FastAPI Request, extracts the x-session-id header
    and returns a mutable AzureSession object.
    Falls back to JWT token to populate user_id if the Redis session is empty.
    """
    # Try to grab explicit session id header first
    session_id = req.headers.get("x-session-id")
    if not session_id:
        val = req.headers.get("Cookie", "")
        if "session_id=" in val:
            for piece in val.split(";"):
                piece = piece.strip()
                if piece.startswith("session_id="):
                    session_id = piece.replace("session_id=", "")

    session = AzureSession(session_id=session_id)

    # If the session has no user_id, try to populate it from the JWT Bearer token.
    # This allows JWT-authenticated routes (which don't send an x-session-id) to
    # still call session.get('user_id') without getting None.
    if not session.get("user_id"):
        try:
            auth_header = req.headers.get("Authorization", "")
            if auth_header.startswith("Bearer "):
                token = auth_header.split(" ", 1)[1]
                import jwt as _jwt
                import os as _os
                secret = _os.getenv("JWT_SECRET_KEY") or _os.getenv("SECRET_KEY", "")
                payload = _jwt.decode(token, secret, algorithms=["HS256"])
                session._data["user_id"] = payload.get("user_id")
                session._data["user_role"] = payload.get("role", "user")
        except Exception as e:
            logging.debug(f"[AzureSession] JWT fallback failed (ok if no token): {e}")

    return session
