
import logging
import threading
import time
from common.ai.llm.config import GOOGLE_API_KEY, GOOGLE_API_KEY1, _GOOGLE_MAX_TOKENS, KEY_ROTATION_BACKOFF_SECS

logger = logging.getLogger(__name__)

_GOOGLE_KEY_FLASH_LITE = GOOGLE_API_KEY
_GOOGLE_KEY_PRO = GOOGLE_API_KEY1
_GOOGLE_KEY_POOL = [k for k in [GOOGLE_API_KEY, GOOGLE_API_KEY1] if k]
_google_key_index = 0
_google_key_lock = threading.Lock()

def get_google_key_for_tier(tier: str) -> str | None:
    if tier == "pro":
        return _GOOGLE_KEY_PRO or _GOOGLE_KEY_FLASH_LITE or (_GOOGLE_KEY_POOL[0] if _GOOGLE_KEY_POOL else None)
    return _GOOGLE_KEY_FLASH_LITE or (_GOOGLE_KEY_POOL[0] if _GOOGLE_KEY_POOL else None)

def rotate_google_key() -> bool:
    global _google_key_index
    if len(_GOOGLE_KEY_POOL) < 2:
        logger.warning("[LLM_MANAGER] Key rotation skipped — pool has only %d Gemini key(s).", len(_GOOGLE_KEY_POOL))
        return False

    with _google_key_lock:
        old_index = _google_key_index
        _google_key_index = (_google_key_index + 1) % len(_GOOGLE_KEY_POOL)
        new_index = _google_key_index

    logger.warning("[LLM_MANAGER] Google key rotated: slot %d → slot %d. Sleeping %.1fs.", old_index, new_index, KEY_ROTATION_BACKOFF_SECS)
    time.sleep(KEY_ROTATION_BACKOFF_SECS)

    try:
        from common.ai.llm.manager import clear_llm_cache
        clear_llm_cache()
    except Exception:
        pass
    return True

def create_google_llm(model_name: str, tier: str, temperature: float, search_enabled: bool, token_callback, api_key_override: str | None = None):
    from langchain_google_genai import ChatGoogleGenerativeAI
    api_key = api_key_override or get_google_key_for_tier(tier)
    if not api_key:
        raise ValueError("No Google API key configured. Set GOOGLE_API_KEY in your .env file.")

    kwargs = {
        "model": model_name,
        "google_api_key": api_key,
        "temperature": temperature,
        "max_output_tokens": _GOOGLE_MAX_TOKENS.get(tier, 16384),
        "request_timeout": 600,
        "callbacks": [token_callback],
    }
    if search_enabled:
        kwargs["model_kwargs"] = {"google_search_retrieval": True}

    return ChatGoogleGenerativeAI(**kwargs)
