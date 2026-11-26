"""
Startup Configuration Validator

Validates all required and optional environment variables at application startup.
Logs clear warnings/errors so misconfigurations are caught at boot, not at the
first user request.

Usage (in main.py, after load_dotenv()):
    from common.helpers.config_validator import validate_config
    validate_config()
"""

import logging
import os


logger = logging.getLogger(__name__)

# ============================================================================
# VALIDATION RULES
# ============================================================================

_PROVIDER_KEY_RULES: list[tuple[str, str | None, str]] = [
    ("GOOGLE_API_KEY",      "LLM_PROVIDER=google",     "Google Gemini primary API key"),
    ("OPEN_API_KEY",        "LLM_PROVIDER=openai",     "OpenAI API key"),
    ("ANTHROPIC_API_KEY",   "LLM_PROVIDER=anthropic",  "Anthropic Claude API key"),
    ("XAI_API_KEY",         "LLM_PROVIDER=grok",       "xAI Grok API key"),
    ("AZURE_KIMI_API_KEY",  "LLM_PROVIDER=kimi",       "Azure Kimi API key"),
]

_OPTIONAL_RULES: list[tuple[str, str]] = [
    ("GOOGLE_API_KEY1",       "Google Custom Search API key (restricted to Custom Search API only)"),
    ("FALLBACK_LLM_PROVIDER", "Cross-provider fallback (google|openai|anthropic|grok)"),
    ("LLM_PROVIDER",          "Active LLM provider — defaults to 'google' if unset"),
]

_REQUIRED_INFRA: list[tuple[str, str]] = [
    ("MONGODB_URI",      "MongoDB connection string"),
    ("SECRET_KEY",       "Application session secret key"),
]

_OPTIONAL_INFRA: list[tuple[str, str]] = [
    ("AZURE_STORAGE_CONNECTION_STRING", "Azure Blob storage connection"),
    ("REDIS_URL",                       "Redis URL for session/caching"),
    ("DISABLE_HEALTH_EMAIL_NOTIFICATIONS", "Set to 'true' to silence health alert emails"),
]


def validate_config(strict: bool = False) -> bool:
    provider = os.getenv("LLM_PROVIDER", "google").lower().strip()
    fallback  = os.getenv("FALLBACK_LLM_PROVIDER", "").lower().strip()

    errors:   list[str] = []
    warnings: list[str] = []

    logger.info("=" * 60)
    logger.info("[CONFIG] Starting environment validation")
    logger.info(f"[CONFIG] Active provider  : {provider}")

    for var, desc in _REQUIRED_INFRA:
        val = os.getenv(var)
        if not val:
            errors.append(f"{var} — {desc}")

    for var, condition, desc in _PROVIDER_KEY_RULES:
        required_provider = condition.split("=")[1]
        is_active   = (provider  == required_provider)
        is_fallback = (fallback  == required_provider)
        if is_active or is_fallback:
            val = os.getenv(var)
            if not val and var != "XAI_API_KEY":
                role = "primary" if is_active else "fallback"
                errors.append(f"{var} — {desc} (needed for {role} provider '{required_provider}')")
            elif not val and var == "XAI_API_KEY" and not os.getenv("GROK_API_KEY"):
                role = "primary" if is_active else "fallback"
                errors.append(f"{var} or GROK_API_KEY — {desc} (needed for {role} provider '{required_provider}')")

    if warnings:
        logger.warning("[CONFIG] Optional config warnings:")
        for w in warnings:
            logger.warning(f"[CONFIG]   ⚠  {w}")

    if errors:
        logger.error("[CONFIG] MISSING REQUIRED CONFIGURATION:")
        for e in errors:
            logger.error(f"[CONFIG]   ✗  {e}")
        return False

    return True

_REQUIRED_EQUIPMENT_FIELDS: list[tuple[str, str, str]] = [
    ("asset",    "model",         "Equipment model"),
    ("asset",    "serial_number", "Serial number"),
    ("location", "site",          "Site"),
    ("location", "plant",         "Plant"),
    ("location", "area",          "Area"),
]

def validate_required_equipment_fields(config_data: dict) -> tuple[bool, list[str]]:
    missing: list[str] = []
    for section, field, label in _REQUIRED_EQUIPMENT_FIELDS:
        section_data = config_data.get(section, {})
        val = section_data.get(field, "") if isinstance(section_data, dict) else ""
        if not (isinstance(val, str) and val.strip()):
            missing.append(label)
    return (len(missing) == 0, missing)
