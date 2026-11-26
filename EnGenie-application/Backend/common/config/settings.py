"""Environment-based settings and shared constants."""
import os

# ── JWT ────────────────────────────────────────────────────────────────────
_secret_key = os.getenv("SECRET_KEY", "super-secret-key-fallback-for-dev")
_jwt_secret = os.getenv("JWT_SECRET_KEY", _secret_key)

JWT_SECRET_KEY = _jwt_secret
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 8

# ── CORS origins ───────────────────────────────────────────────────────────
_production_origins = [
    "https://engenieai.com",
    "https://www.engenieai.com",
    "https://engenieai.com/",
    "https://www.engenieai.com/"
]

_dev_origins = [
    "http://localhost:8080",
    "http://localhost:5173",
    "http://localhost:3000",
]

_is_production = (
    os.getenv("AZURE_ENV", os.getenv("azure-env", os.getenv("azure_env", "")))
    == "production"
)

allowed_origins = _production_origins.copy()
if not _is_production:
    allowed_origins.extend(_dev_origins)

if os.environ.get("VERCEL") == "1":
    prod_url = os.environ.get("VERCEL_URL")
    if prod_url:
        allowed_origins.append(f"https://{prod_url}")
    branch_url = os.environ.get("VERCEL_BRANCH_URL")
    if branch_url and branch_url != prod_url:
        allowed_origins.append(f"https://{branch_url}")

# ── Azure prefix whitelist ─────────────────────────────────────────────────
ALLOWED_AZURE_PREFIXES = ["engenie", "en-genie", "product-recommender"]

# ── File upload limits ─────────────────────────────────────────────────────
MAX_FILE_SIZE_MB = 100
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


def get_base_url() -> str:
    """Return the base URL of this server for health-monitor registration."""
    port = os.getenv("PORT", "5000")
    host = os.getenv("HOST", "0.0.0.0")
    if host in ("0.0.0.0", ""):
        host = "127.0.0.1"
    return f"http://{host}:{port}"
