
import logging
import os
from functools import lru_cache
from common.ai.llm.config import (
    LLM_PROVIDER, SOLUTION_LLM_PROVIDER, FALLBACK_LLM_PROVIDER,
    PROVIDER_MODELS, TEMP_DETERMINISTIC, TEMP_CREATIVE, TEMP_BALANCED,
)
from common.ai.llm.tracking import TokenUsageCallbackHandler
from common.ai.llm.providers.deepinfra import create_deepinfra_llm

# --- Commented out other providers (DeepInfra only) ---
# from common.ai.llm.providers.google import create_google_llm, get_google_key_for_tier, _GOOGLE_KEY_POOL
# from common.ai.llm.providers.openai import create_openai_llm
# from common.ai.llm.providers.anthropic import create_anthropic_llm
# from common.ai.llm.providers.grok import create_grok_llm

logger = logging.getLogger(__name__)

def _get_model_name(tier: str, provider: str | None = None) -> str:
    effective_provider = provider or LLM_PROVIDER
    models = PROVIDER_MODELS.get(effective_provider)
    if not models:
        # Fallback to deepinfra models if provider name mismatch
        models = PROVIDER_MODELS.get("deepinfra", {})
    return models.get(tier, "Qwen/Qwen3-VL-30B-A3B-Instruct")

# Rate-limit (429/quota) retries are paced separately from transient-fault
# retries: provider quotas are PER-MINUTE, so sub-second jitter just hammers the
# exhausted window (and burns RPM). Start at ~20s so the retry lands in a fresh
# quota window.
_RATELIMIT_RETRY_ATTEMPTS = int(os.getenv("LLM_RATELIMIT_RETRY_ATTEMPTS", "3"))
_RATELIMIT_RETRY_INITIAL_SECS = float(os.getenv("LLM_RATELIMIT_RETRY_INITIAL_SECS", "20"))


def _wrap_with_retry(llm):
    """Two-tier retry policy:

    - transient network/server faults -> quick retry (~1s exponential jitter)
    - rate-limit / quota exhaustion   -> slow retry (~20s+ exponential jitter)
    - hard client errors (404 DeploymentNotFound, 400 bad request, auth) -> NO
      retry.
    """
    from httpx import ConnectError, ReadTimeout, WriteTimeout, RequestError
    from requests.exceptions import ConnectionError, Timeout
    from urllib3.exceptions import NewConnectionError, ProtocolError

    _transient = [
        ConnectionError, Timeout, ProtocolError, NewConnectionError, ConnectError,
        ReadTimeout, WriteTimeout, TimeoutError, OSError, RequestError,
    ]
    _rate_limited = []

    try:
        import openai
        _transient += [openai.APIConnectionError, openai.APITimeoutError, openai.InternalServerError]
        _rate_limited.append(openai.RateLimitError)
    except ImportError: pass

    wrapped = llm.with_retry(
        retry_if_exception_type=tuple(_transient),
        stop_after_attempt=3, wait_exponential_jitter=True,
    )
    if _rate_limited and _RATELIMIT_RETRY_ATTEMPTS > 1:
        wrapped = wrapped.with_retry(
            retry_if_exception_type=tuple(_rate_limited),
            stop_after_attempt=_RATELIMIT_RETRY_ATTEMPTS,
            wait_exponential_jitter=True,
            exponential_jitter_params={"initial": _RATELIMIT_RETRY_INITIAL_SECS},
        )
    return wrapped

def _create_llm(tier: str, temperature: float = 0.1, search_enabled: bool = False, provider: str | None = None, api_key_override: str | None = None, allow_fallback: bool = True):
    effective_provider = "deepinfra"
    model_name = _get_model_name(tier, effective_provider)
    token_callback = TokenUsageCallbackHandler(model_name=model_name, provider=effective_provider)

    logger.info(f"Creating LLM: provider={effective_provider}, model={model_name}, tier={tier}, temp={temperature}, search={search_enabled}")

    # DeepInfra is the exclusive active provider
    return create_deepinfra_llm(model_name, tier, temperature, search_enabled, token_callback)

@lru_cache(maxsize=16)
def get_flash_llm(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("flash", temperature))

@lru_cache(maxsize=8)
def get_pro_llm(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("pro", temperature))

@lru_cache(maxsize=8)
def get_lite_llm(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("lite", temperature))

@lru_cache(maxsize=8)
def get_flash_with_search(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("flash", temperature, search_enabled=False))

@lru_cache(maxsize=8)
def get_solution_pro_llm(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("pro", temperature, provider=SOLUTION_LLM_PROVIDER))

@lru_cache(maxsize=8)
def get_solution_flash_llm(temperature: float = 0.1):
    return _wrap_with_retry(_create_llm("flash", temperature, provider=SOLUTION_LLM_PROVIDER))

def clear_llm_cache():
    logger.info("Clearing all cached LLM instances")
    get_flash_llm.cache_clear()
    get_pro_llm.cache_clear()
    get_lite_llm.cache_clear()
    get_flash_with_search.cache_clear()
    get_solution_pro_llm.cache_clear()
    get_solution_flash_llm.cache_clear()

def with_json_mode(llm, provider: str | None = None):
    """Pass-through for DeepInfra models where JSON output is enforced via system prompts."""
    return llm

def get_llm_for_task(task_type: str, temperature: float = 0.1):
    task_map = {'simple': get_lite_llm, 'medium': get_flash_llm, 'complex': get_pro_llm, 'search': get_flash_with_search}
    if task_type not in task_map: raise ValueError(f"Invalid task_type: {task_type}.")
    return task_map[task_type](temperature)

def get_deterministic_flash(): return get_flash_llm(temperature=TEMP_DETERMINISTIC)
def get_creative_flash(): return get_flash_llm(temperature=TEMP_CREATIVE)
def get_deterministic_pro(): return get_pro_llm(temperature=TEMP_DETERMINISTIC)
def get_creative_pro(): return get_pro_llm(temperature=TEMP_CREATIVE)
def get_default_llm(): return get_deterministic_flash()
def get_creative_llm(): return get_creative_flash()

def get_provider_info() -> dict:
    models = PROVIDER_MODELS.get("deepinfra", {})
    return {
        "provider": "deepinfra",
        "models": models,
        "supported_providers": ["deepinfra"],
        "api_key_set": {
            "deepinfra": bool(os.getenv("DEEPINFRA_API_KEY")),
            # "google": False,
            # "openai": False,
            # "anthropic": False,
            # "grok": False,
            # "kimi": False,
            # "replicate": False,
        },
        "search_supported": False,
    }
