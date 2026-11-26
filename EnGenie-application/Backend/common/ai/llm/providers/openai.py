
import logging
import os
import threading
from common.ai.llm.config import (
    OPEN_API_KEY, OPEN_API_KEY1, LLM_PROVIDER,
    AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_VERSION, AZURE_OPENAI_DEPLOYMENTS,
    _OPENAI_MAX_TOKENS,
)

logger = logging.getLogger(__name__)

# SDK-level retries default to 0: the manager's with_retry layer is the single
# retry control point (same fix as providers/kimi.py — the OpenAI client's
# built-in retries otherwise stack multiplicatively under the manager's
# tenacity retries, hammering a rate-limited deployment with sub-second bursts).
_OPENAI_SDK_MAX_RETRIES = int(os.getenv("OPENAI_SDK_MAX_RETRIES", "0"))

# Reasoning effort for gpt-5*/o* reasoning models. Their hidden thinking tokens
# bill as OUTPUT tokens and add latency. flash/lite run classification and
# formatting where "low" loses little and cuts output ~50%. Pro deliberately
# gets NO effort param: the server default is medium anyway, and sending the
# param forces temperature=1 (Azure rejects the pipeline's 0.1 alongside it),
# which made the holistic gate verdict non-deterministic in A/B testing.
# Override every tier with OPENAI_REASONING_EFFORT, or per tier with
# OPENAI_REASONING_EFFORT_<TIER>.
_REASONING_EFFORT_DEFAULTS = {"pro": "", "flash": "low", "lite": "low"}


def _reasoning_effort_for(tier: str) -> str | None:
    effort = (os.getenv(f"OPENAI_REASONING_EFFORT_{tier.upper()}", "").strip()
              or os.getenv("OPENAI_REASONING_EFFORT", "").strip()
              or _REASONING_EFFORT_DEFAULTS.get(tier, "")).lower()
    return effort if effort in {"minimal", "low", "medium", "high"} else None


def _apply_reasoning_effort(llm_kwargs: dict, tier: str) -> None:
    effort = _reasoning_effort_for(tier)
    if effort:
        llm_kwargs["reasoning_effort"] = effort

_azure_key_index = 0
_azure_key_lock = threading.Lock()

_HAS_OPENAI = bool(OPEN_API_KEY)
# Use Azure if: endpoint is explicitly set, OR provider is 'openai' (key is Azure Foundry key, not sk-...)
_HAS_AZURE = bool(AZURE_OPENAI_ENDPOINT and OPEN_API_KEY) or (
    LLM_PROVIDER == "openai" and bool(OPEN_API_KEY) and not OPEN_API_KEY.startswith("sk-")
)


def _get_next_azure_key() -> str:
    global _azure_key_index
    keys = [k for k in [OPEN_API_KEY, OPEN_API_KEY1] if k]
    with _azure_key_lock:
        key = keys[_azure_key_index % len(keys)]
        _azure_key_index += 1
    return key


def _build_azure_llm(tier: str, temperature: float, token_callback):
    import os
    from langchain_openai import AzureChatOpenAI
    api_key = _get_next_azure_key()
    # Re-read at call time in case env var was injected after module import
    endpoint = AZURE_OPENAI_ENDPOINT or os.getenv("AZURE_OPENAI_ENDPOINT", "").strip()
    if not endpoint:
        raise ValueError(
            "AZURE_OPENAI_ENDPOINT is not set. "
            "Add it as a Secret reference env var in Azure Container Apps pointing to 'azure-openai-endpoint'."
        )
    deployment = AZURE_OPENAI_DEPLOYMENTS.get(tier, "gpt-4o")
    logger.debug("[OpenAI] Azure — endpoint=%s deployment=%s tier=%s", endpoint, deployment, tier)
    # Report cost against the deployment actually served, not the logical tier
    # model: with pro remapped to gpt-5.4-mini, tracking priced calls as gpt-5.4
    # ($75/M input) — overstating real cost ~75x in usage dashboards.
    token_callback.model_name = deployment
    
    is_reasoning = "gpt-5" in deployment.lower() or "o1" in deployment.lower() or "o3" in deployment.lower()
    llm_kwargs = {
        "azure_endpoint": endpoint,
        "azure_deployment": deployment,
        "api_version": AZURE_OPENAI_API_VERSION,
        "api_key": api_key,
        "temperature": temperature,
        "timeout": 600,
        "max_retries": _OPENAI_SDK_MAX_RETRIES,
        "callbacks": [token_callback],
    }
    if is_reasoning:
        llm_kwargs["max_completion_tokens"] = _OPENAI_MAX_TOKENS.get(tier, 16384)
        _apply_reasoning_effort(llm_kwargs, tier)
        # With reasoning_effort present Azure strictly validates temperature
        # (400 unsupported_value for the pipeline's 0.1); without the param the
        # caller's temperature is accepted, so only override when effort is set.
        if "reasoning_effort" in llm_kwargs:
            llm_kwargs["temperature"] = 1
    else:
        llm_kwargs["max_tokens"] = _OPENAI_MAX_TOKENS.get(tier, 16384)

    try:
        return AzureChatOpenAI(**llm_kwargs)
    except TypeError:
        # Older langchain_openai without first-class reasoning_effort: route it
        # through model_kwargs instead (mirrors the kimi provider's fallback).
        effort = llm_kwargs.pop("reasoning_effort", None)
        if effort is None:
            raise
        llm_kwargs.setdefault("model_kwargs", {})["reasoning_effort"] = effort
        return AzureChatOpenAI(**llm_kwargs)


def _build_openai_llm(model_name: str, tier: str, temperature: float, token_callback):
    from langchain_openai import ChatOpenAI
    logger.debug("[OpenAI] Regular — model=%s tier=%s", model_name, tier)
    
    is_reasoning = "gpt-5" in model_name.lower() or "o1" in model_name.lower() or "o3" in model_name.lower()
    llm_kwargs = {
        "model": model_name,
        "api_key": OPEN_API_KEY,
        "temperature": temperature,
        "timeout": 600,
        "max_retries": _OPENAI_SDK_MAX_RETRIES,
        "callbacks": [token_callback],
    }
    if is_reasoning:
        llm_kwargs["max_completion_tokens"] = _OPENAI_MAX_TOKENS.get(tier, 16384)
        _apply_reasoning_effort(llm_kwargs, tier)
        if "reasoning_effort" in llm_kwargs:
            llm_kwargs["temperature"] = 1
    else:
        llm_kwargs["max_tokens"] = _OPENAI_MAX_TOKENS.get(tier, 16384)

    try:
        return ChatOpenAI(**llm_kwargs)
    except TypeError:
        effort = llm_kwargs.pop("reasoning_effort", None)
        if effort is None:
            raise
        llm_kwargs.setdefault("model_kwargs", {})["reasoning_effort"] = effort
        return ChatOpenAI(**llm_kwargs)


def create_openai_llm(model_name: str, tier: str, temperature: float, search_enabled: bool, token_callback):
    if search_enabled:
        logger.warning("[OpenAI] Web search is Google-specific. Using standard model.")

    if not _HAS_OPENAI and not _HAS_AZURE:
        raise ValueError("No OpenAI API key configured. Set OPEN_API_KEY or AZURE_OPENAI_API_KEY.")

    # If Azure endpoint is configured, OPEN_API_KEY is an Azure key — always route through Azure
    if _HAS_AZURE:
        logger.debug("[OpenAI] Mode: Azure primary (Foundry)")
        return _build_azure_llm(tier, temperature, token_callback)

    # No Azure endpoint → standard OpenAI
    return _build_openai_llm(model_name, tier, temperature, token_callback)
