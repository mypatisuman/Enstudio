import logging
import threading
import os
from common.ai.llm.config import _KIMI_MAX_TOKENS

logger = logging.getLogger(__name__)

# Key rotation for Kimi
_kimi_key_index = 0
_kimi_key_lock = threading.Lock()

# Reasoning effort for Kimi K2.5/K2.6 (thinking models). These models share a
# single fixed completion-token budget between the reasoning trace and the final
# answer. Keeping reasoning effort low frees that fixed budget for the actual
# response — fixing truncated/empty output WITHOUT raising any token limit.
# Override via KIMI_REASONING_EFFORT ("minimal" | "low" | "medium" | "high").
_KIMI_REASONING_EFFORT = os.getenv("KIMI_REASONING_EFFORT", "low").strip().lower()

# Per-request timeout (seconds). Kept generous so long, legitimate extractions
# are NOT killed mid-flight. Streaming keeps the connection active between
# chunks so this acts as an overall ceiling, not an idle cut-off.
_KIMI_TIMEOUT = float(os.getenv("KIMI_TIMEOUT", "600"))

# Stream by default. With streaming, .invoke() still returns a complete
# aggregated message (transparent to callers and JSON parsers), but tokens
# arrive incrementally so a long generation no longer has to land in a single
# blocking read — the main defence against read-timeouts on slow thinking models.
_KIMI_STREAMING = os.getenv("KIMI_STREAMING", "true").strip().lower() in {"1", "true", "yes", "on"}

# SDK-level retries default to 0: the manager's with_retry layer is the single
# retry control point. The OpenAI client's built-in retries (default 2) nested
# inside the manager's tenacity retries (3) produced up to 9 HTTP attempts per
# logical call — a sub-second 429 storm that also burned the RPM quota.
_KIMI_SDK_MAX_RETRIES = int(os.getenv("KIMI_SDK_MAX_RETRIES", "0"))

# Process-wide pacing shared by every Kimi client (all tiers/temperatures).
# Azure debits prompt + max_completion_tokens from the TPM quota at request
# start, so unpaced parallel graph nodes + background memory threads exhaust a
# small quota within seconds. Per-process only — lower KIMI_MAX_RPM when
# running multiple workers. 0 disables the limiter.
_KIMI_MAX_RPM = float(os.getenv("KIMI_MAX_RPM", "10"))
_KIMI_RATE_LIMITER = None
if _KIMI_MAX_RPM > 0:
    try:
        from langchain_core.rate_limiters import InMemoryRateLimiter
        _KIMI_RATE_LIMITER = InMemoryRateLimiter(
            requests_per_second=_KIMI_MAX_RPM / 60.0,
            check_every_n_seconds=0.5,
            max_bucket_size=max(1.0, _KIMI_MAX_RPM / 5.0),
        )
    except ImportError:
        logger.warning("[Kimi] langchain_core.rate_limiters unavailable; running without client-side RPM pacing.")


def _get_next_kimi_key() -> str:
    global _kimi_key_index
    api_key = os.getenv("AZURE_KIMI_API_KEY")
    api_key1 = os.getenv("AZURE_KIMI_API_KEY1")
    keys = [k for k in [api_key, api_key1] if k]
    if not keys:
        raise ValueError("AZURE_KIMI_API_KEY is not configured in the environment.")
    with _kimi_key_lock:
        key = keys[_kimi_key_index % len(keys)]
        _kimi_key_index += 1
    return key

from langchain_openai import AzureChatOpenAI

# System-level instruction that keeps Kimi's reasoning concise and objective.
# Paired with reasoning_effort=low, this protects the shared completion budget so
# the model spends its fixed token allowance on the answer, not the scratchpad.
_KIMI_SYSTEM_INSTRUCTION = (
    "Keep your reasoning extremely concise and focused strictly on the technical and "
    "engineering requirements. Ensure all analysis, calculations, and explanations are "
    "purely scientific, objective, and neutral, avoiding speculative or non-technical "
    "language. Spend your token budget on the final detailed answer rather than on "
    "lengthy internal deliberation."
)


def _with_system_instruction(input):
    """Prepend / merge the reasoning-control system instruction onto any LangChain
    input form (str, message list, or PromptValue). Shared by all invocation paths
    so the instruction is applied consistently on invoke/stream/async — not just
    the sync invoke() path."""
    from langchain_core.messages import SystemMessage, HumanMessage

    if isinstance(input, str):
        return [SystemMessage(content=_KIMI_SYSTEM_INSTRUCTION), HumanMessage(content=input)]

    if isinstance(input, list):
        if input and isinstance(input[0], SystemMessage):
            combined = f"{input[0].content}\n\n{_KIMI_SYSTEM_INSTRUCTION}"
            return [SystemMessage(content=combined)] + input[1:]
        return [SystemMessage(content=_KIMI_SYSTEM_INSTRUCTION)] + input

    # PromptValue or other objects exposing .to_messages()
    try:
        msgs = input.to_messages()
    except AttributeError:
        return input
    if msgs and isinstance(msgs[0], SystemMessage):
        combined = f"{msgs[0].content}\n\n{_KIMI_SYSTEM_INSTRUCTION}"
        return [SystemMessage(content=combined)] + msgs[1:]
    return [SystemMessage(content=_KIMI_SYSTEM_INSTRUCTION)] + msgs


class KimiAzureChatOpenAI(AzureChatOpenAI):
    """AzureChatOpenAI wrapper for Kimi that injects a reasoning-control system
    instruction on every invocation path (sync, async, streaming) so the model's
    fixed completion budget is preserved for the final answer."""

    def invoke(self, input, config=None, **kwargs):
        return super().invoke(_with_system_instruction(input), config, **kwargs)

    async def ainvoke(self, input, config=None, **kwargs):
        return await super().ainvoke(_with_system_instruction(input), config, **kwargs)

    def stream(self, input, config=None, **kwargs):
        return super().stream(_with_system_instruction(input), config, **kwargs)

    async def astream(self, input, config=None, **kwargs):
        async for chunk in super().astream(_with_system_instruction(input), config, **kwargs):
            yield chunk


def create_kimi_llm(model_name: str, tier: str, temperature: float, search_enabled: bool, token_callback):
    if search_enabled:
        logger.warning("[Kimi] Web search is a Google-specific feature. Using standard model.")

    endpoint = os.getenv("AZURE_KIMI_ENDPOINT", "").strip()
    if not endpoint:
        raise ValueError("AZURE_KIMI_ENDPOINT is not set in the environment.")

    api_key = _get_next_kimi_key()
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2023-05-15")
    max_tokens = _KIMI_MAX_TOKENS.get(tier, 16384)

    logger.debug(
        "[Kimi] Creating primary KimiAzureChatOpenAI: deployment=%s, endpoint=%s, "
        "reasoning_effort=%s, streaming=%s, max_tokens=%s, timeout=%ss",
        model_name, endpoint, _KIMI_REASONING_EFFORT, _KIMI_STREAMING, max_tokens, _KIMI_TIMEOUT,
    )

    common_kwargs = dict(
        azure_endpoint=endpoint,
        api_version=api_version,
        api_key=api_key,
        temperature=temperature,
        max_completion_tokens=max_tokens,
        timeout=_KIMI_TIMEOUT,
        streaming=_KIMI_STREAMING,
        max_retries=_KIMI_SDK_MAX_RETRIES,
        callbacks=[token_callback],
        # reasoning_effort is a first-class param on current langchain_openai.
        # _build falls back to model_kwargs on older builds that lack it.
        reasoning_effort=_KIMI_REASONING_EFFORT,
    )

    # stream_usage ensures token counts are still reported when streaming is on.
    # Older langchain_openai builds don't accept it, so add it defensively.
    if _KIMI_STREAMING:
        common_kwargs["stream_usage"] = True

    def _build(cls, **overrides):
        kwargs = {**common_kwargs, **overrides}
        for _ in range(3):  # progressively drop unsupported kwargs, then give up
            try:
                return cls(**kwargs)
            except TypeError as e:
                msg = str(e)
                if "reasoning_effort" in kwargs and "reasoning_effort" in msg:
                    # Older langchain_openai: pass via model_kwargs instead.
                    logger.warning("[Kimi] reasoning_effort not a direct param (%s); routing via model_kwargs.", e)
                    eff = kwargs.pop("reasoning_effort")
                    kwargs.setdefault("model_kwargs", {})["reasoning_effort"] = eff
                    continue
                if "stream_usage" in kwargs and "stream_usage" in msg:
                    logger.warning("[Kimi] stream_usage unsupported by langchain_openai (%s); dropping it.", e)
                    kwargs.pop("stream_usage", None)
                    continue
                raise
        return cls(**kwargs)

    # 1. Primary Kimi LLM (reasoning-optimized + streaming). The rate limiter
    #    applies to the primary only — the GPT fallback lives on a different
    #    Azure resource with its own quota.
    primary_overrides = {"azure_deployment": model_name}
    if _KIMI_RATE_LIMITER is not None:
        primary_overrides["rate_limiter"] = _KIMI_RATE_LIMITER
    primary_llm = _build(KimiAzureChatOpenAI, **primary_overrides)

    # 2. Fallback GPT LLM. The gpt-5.4* deployments live on the AZURE_OPENAI_ENDPOINT
    #    resource, NOT on the Kimi resource — pointing the fallback at the Kimi
    #    endpoint made every failover die with 404 DeploymentNotFound, so the
    #    original error (e.g. 429) was re-raised and the "failover" never worked.
    #    Override temperature to 1.0 because reasoning fallback models
    #    (gpt-5.4 / gpt-5.4-mini) do not support temperature=0.1.
    fallback_endpoint = (os.getenv("AZURE_KIMI_FALLBACK_ENDPOINT", "").strip()
                         or os.getenv("AZURE_OPENAI_ENDPOINT", "").strip())
    fallback_key = (os.getenv("AZURE_KIMI_FALLBACK_API_KEY", "").strip()
                    or os.getenv("OPEN_API_KEY", "").strip())
    if not fallback_endpoint or not fallback_key:
        logger.warning(
            "[Kimi] No GPT fallback configured (need AZURE_OPENAI_ENDPOINT + OPEN_API_KEY "
            "or AZURE_KIMI_FALLBACK_ENDPOINT + AZURE_KIMI_FALLBACK_API_KEY); "
            "running without failover."
        )
        return primary_llm

    from common.ai.llm.config import AZURE_OPENAI_DEPLOYMENTS
    fallback_deployment = AZURE_OPENAI_DEPLOYMENTS.get(tier) or ("gpt-5.4" if tier == "pro" else "gpt-5.4-mini")
    fallback_api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2025-01-01-preview")
    logger.debug(
        "[Kimi] Configuring fallback AzureChatOpenAI: endpoint=%s, deployment=%s",
        fallback_endpoint, fallback_deployment,
    )
    fallback_llm = _build(
        AzureChatOpenAI,
        azure_endpoint=fallback_endpoint,
        api_key=fallback_key,
        api_version=fallback_api_version,
        azure_deployment=fallback_deployment,
        temperature=1.0,
    )

    # Return primary Kimi LLM with automatic failover to GPT
    return primary_llm.with_fallbacks([fallback_llm])
