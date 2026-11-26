"""
DeepInfra Provider for Gemma Models
===================================
Default Model: google/gemma-4-31B-it-turbo
Endpoint:      https://api.deepinfra.com/v1/openai

Model Tiers & Temperatures:
---------------------------
1. REASONING / PRO (Temperature: 0.1)
   Used for complex engineering reasoning, BOM generation, and parameter deduction:
   - holistic_agent.py        -> Evaluates engineering completeness & builds BOM
   - infer_agent.py           -> Deduces physical specs (pressure, temp, materials)
   - solution_build_agent.py  -> Generates engineering system design narrative
   - expansion_agent.py       -> Extracts L3 specs from manufacturer datasheets
   - solution_agent.py        -> Processes multi-item BOM modifications
   - vendor_analysis_agent.py -> Deep vendor datasheet and specification analysis

2. FLASH (Temperature: 0.1)
   Used for fast intent routing, candidate verification, validation, and chat formatting:
   - solution_agent.py        -> Classifies project intent (requirements vs modification)
   - episodic_recall_agent.py -> Verifies similar past project candidates
   - search_agent.py          -> Classifies search query intent & formats answer
   - validation_agent.py      -> Validates specs & maps taxonomy
   - vendor_ranking_agent.py  -> Scores and ranks vendor products
   - format_results_agent.py  -> Formats conversational output for chat
   - harness_agent.py         -> Validates standards compliance & repairs JSON

3. LITE (Temperature: 0.1)
   Used for fast entity matching and user preference memory:
   - hybrid_memory_manager.py -> Summarizes user procurement profile
   - identify_vendors_agent   -> Fuzzy-matches vendor names
"""

import inspect
import logging
import os
import time
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)

# Configuration
_BASE_URL = os.getenv("DEEPINFRA_BASE_URL", "https://api.deepinfra.com/v1/openai")
# Default None lets the LLM model generate up to its native maximum output token limit
_MAX_TOKENS_ENV = os.getenv("DEEPINFRA_MAX_TOKENS", "").strip()
_MAX_TOKENS = int(_MAX_TOKENS_ENV) if _MAX_TOKENS_ENV and _MAX_TOKENS_ENV.isdigit() and int(_MAX_TOKENS_ENV) > 0 else None
_TIMEOUT = float(os.getenv("DEEPINFRA_TIMEOUT", "300"))
_STREAMING = os.getenv("DEEPINFRA_STREAMING", "true").strip().lower() in {"1", "true", "yes", "on"}


def _get_caller_info() -> tuple[str, str]:
    """Finds the agent name and function that triggered the LLM call."""
    try:
        for frame in inspect.stack():
            path = frame.filename.replace("\\", "/")
            if "domain/solution" in path or "domain/search" in path or "domain/" in path:
                agent = path.split("/")[-1].replace(".py", "")
                return agent, frame.function
    except Exception:
        pass
    return "UnknownAgent", "invoke"


class DeepInfraTraceHandler(BaseCallbackHandler):
    """Logs clear, human-readable execution traces for every DeepInfra LLM call."""

    def __init__(self, model_name: str, tier: str, temperature: float):
        super().__init__()
        self.model_name = model_name
        self.tier = "REASONING (PRO)" if "pro" in tier.lower() else tier.upper()
        self.temperature = temperature
        self._start_times: dict[str, float] = {}

    def on_chat_model_start(self, serialized, messages, run_id=None, **kwargs):
        agent, func = _get_caller_info()
        run_key = str(run_id) if run_id else "default"
        self._start_times[run_key] = time.time()

        prompt_preview = ""
        if messages and len(messages) > 0:
            last = messages[0][-1] if isinstance(messages[0], list) and messages[0] else messages[0]
            prompt_preview = str(getattr(last, "content", last))[:140].replace("\n", " ").strip()

        logger.info(
            f"[DeepInfra] 🚀 START | Agent: {agent} -> {func}() | "
            f"Tier: {self.tier} | Temp: {self.temperature} | Model: {self.model_name} | "
            f"Prompt: \"{prompt_preview}...\""
        )

    def on_llm_end(self, response, run_id=None, **kwargs):
        agent, func = _get_caller_info()
        run_key = str(run_id) if run_id else "default"
        elapsed = time.time() - self._start_times.pop(run_key, time.time())

        # Extract token usage if available
        tokens = "N/A"
        try:
            if hasattr(response, "llm_output") and response.llm_output:
                usage = response.llm_output.get("token_usage", {}) or response.llm_output.get("usage", {})
                if usage:
                    tokens = f"{usage.get('total_tokens', 0):,} total ({usage.get('prompt_tokens', 0):,} in, {usage.get('completion_tokens', 0):,} out)"
        except Exception:
            pass

        logger.info(
            f"[DeepInfra] ✅ DONE  | Agent: {agent} -> {func}() | "
            f"Tier: {self.tier} | Duration: {elapsed:.2f}s | Tokens: {tokens}"
        )

    def on_llm_error(self, error: BaseException, run_id=None, **kwargs):
        agent, func = _get_caller_info()
        run_key = str(run_id) if run_id else "default"
        elapsed = time.time() - self._start_times.pop(run_key, time.time())

        logger.error(
            f"[DeepInfra] ❌ ERROR | Agent: {agent} -> {func}() | "
            f"Tier: {self.tier} | Duration: {elapsed:.2f}s | Error: {error}"
        )


def create_deepinfra_llm(model_name: str, tier: str, temperature: float, search_enabled: bool, token_callback) -> ChatOpenAI:
    """Creates a configured ChatOpenAI client pointing to DeepInfra."""
    api_key = os.getenv("DEEPINFRA_API_KEY", "").strip()
    if not api_key:
        raise ValueError("DEEPINFRA_API_KEY is not set in the environment.")

    callbacks = []
    if token_callback:
        callbacks.append(token_callback)
    callbacks.append(DeepInfraTraceHandler(model_name=model_name, tier=tier, temperature=temperature))

    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=_BASE_URL,
        temperature=temperature,
        max_tokens=_MAX_TOKENS,
        timeout=_TIMEOUT,
        max_retries=0,  # Retries are handled by manager.py
        streaming=_STREAMING,
        callbacks=callbacks,
    )
