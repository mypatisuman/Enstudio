"""
adapters/llm_deepinfra.py — DeepInfra LLM provider for EngineeringStudio.

Features:
- OpenAI-compatible API connectivity targeting DeepInfra (https://api.deepinfra.com/v1/openai).
- Environment variable fallback (DEEPINFRA_API_KEY, DEEPINFRA_BASE_URL, DEEPINFRA_MODEL_SMART, DEEPINFRA_MODEL_FAST)
  alongside studio.db SQLite settings storage.
- EnGenie two-tier retry strategy:
  * Tier 1: Transient network/timeout jittered backoff.
  * Tier 2: 20s backoff for HTTP 429 RateLimitError exhaustion (up to 3 retries).
- Execution trace logging with model, tier, duration, and token telemetry:
  * [DeepInfra] 🚀 START | Model: <model> | Tier: <tier>
  * [DeepInfra] ✅ DONE  | Duration: <sec>s | Tokens: <in>/<out>
  * [DeepInfra] ❌ FAILED | Duration: <sec>s | Error: <exc>
"""
from __future__ import annotations

import logging
import os
import random
import time
from typing import Any, Optional

from openai import APIConnectionError, APITimeoutError, RateLimitError

from adapters.llm_openai import OpenAIProvider
from adapters.llm_provider import LLMResponse

logger = logging.getLogger(__name__)

# Default DeepInfra endpoints and model defaults
DEFAULT_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEFAULT_MODEL = "google/gemma-4-31B-it-turbo"

# Estimated cost per million tokens (input / output) for open-weights models on DeepInfra
_DEEPINFRA_COST_RATES: dict[str, tuple[float, float]] = {
    "google/gemma-4-31B-it-turbo": (0.20, 0.40),
    "meta-llama/Llama-3.3-70B-Instruct": (0.23, 0.40),
    "meta-llama/Llama-3.2-11B-Vision-Instruct": (0.18, 0.35),
    "Qwen/Qwen2-VL-72B-Instruct": (0.30, 0.60),
}


def _deepinfra_cost(model: str, tin: int, tout: int) -> float:
    rates = _DEEPINFRA_COST_RATES.get(model, (0.20, 0.40))
    return round((tin * rates[0] + tout * rates[1]) / 1_000_000, 6)


class DeepInfraProvider(OpenAIProvider):
    """DeepInfra provider extending OpenAIProvider with two-tier retry resilience
    and execution trace logging mirroring EnGenie's LLM architecture.
    """

    @property
    def provider_name(self) -> str:
        return "deepinfra"

    def __init__(
        self,
        api_key: str = "",
        model: Optional[str] = None,
        model_fast: Optional[str] = None,
        temperature: float = 0.0,
        base_url: Optional[str] = None,
        provider_label: str = "deepinfra",
    ) -> None:
        # Fallback hierarchy: explicit arg -> environment variable -> default
        resolved_key = (api_key or os.getenv("DEEPINFRA_API_KEY", "")).strip()
        resolved_base_url = (base_url or os.getenv("DEEPINFRA_BASE_URL", DEFAULT_BASE_URL)).strip()
        resolved_smart = (model or os.getenv("DEEPINFRA_MODEL_SMART", DEFAULT_MODEL)).strip()
        resolved_fast = (model_fast or os.getenv("DEEPINFRA_MODEL_FAST", resolved_smart)).strip()

        super().__init__(
            api_key=resolved_key,
            model=resolved_smart,
            model_fast=resolved_fast,
            temperature=temperature,
            base_url=resolved_base_url,
            provider_label=provider_label,
        )
        # DeepInfra adheres to OpenAI standard `max_tokens`
        self._token_param = "max_tokens"
        self._base_url = resolved_base_url

    def _create(self, **kwargs: Any) -> Any:
        """Execute chat completion with EnGenie's two-tier retry strategy:
        1. Transient connection/timeout jitter (up to 3 retries).
        2. 20s backoff for 429 RateLimitError exhaustion (up to 3 retries).
        3. Temperature fallback for models that disallow custom temperature values.
        """
        model: str = kwargs.get("model", "")
        if model in self._no_custom_temperature:
            kwargs.pop("temperature", None)

        max_rate_limit_retries = 3
        rate_limit_attempts = 0

        max_transient_retries = 3
        transient_attempts = 0

        while True:
            try:
                return self._client.chat.completions.create(**kwargs)
            except RateLimitError as rle:
                rate_limit_attempts += 1
                if rate_limit_attempts > max_rate_limit_retries:
                    print(f"[DeepInfra] ❌ Rate limit (429) retry attempts exhausted ({max_rate_limit_retries} attempts).")
                    raise
                # EnGenie 20s rate-limit backoff with jitter
                backoff_secs = 20.0 + random.uniform(0.5, 2.0)
                print(
                    f"[DeepInfra] ⚠️ Rate limit encountered (429). Backing off for {backoff_secs:.1f}s "
                    f"(attempt {rate_limit_attempts}/{max_rate_limit_retries})..."
                )
                time.sleep(backoff_secs)
            except (APIConnectionError, APITimeoutError) as net_err:
                transient_attempts += 1
                if transient_attempts > max_transient_retries:
                    print(f"[DeepInfra] ❌ Transient connection retries exhausted: {net_err}")
                    raise
                jitter_delay = (1.0 * (2 ** (transient_attempts - 1))) + random.uniform(0.1, 0.5)
                print(
                    f"[DeepInfra] ⚠️ Transient network error: {net_err}. Retrying in {jitter_delay:.1f}s "
                    f"(attempt {transient_attempts}/{max_transient_retries})..."
                )
                time.sleep(jitter_delay)
            except Exception as exc:
                # Handle model temperature rejection
                if "temperature" in str(exc) and "does not support" in str(exc):
                    self._no_custom_temperature.add(model)
                    kwargs.pop("temperature", None)
                    continue
                raise

    def complete(
        self,
        prompt: str,
        *,
        max_tokens: int = 8000,
        tier: str = "fast",
    ) -> LLMResponse:
        model = self._model_name(tier)
        print(f"[DeepInfra] 🚀 START | Model: {model} | Tier: {tier}")
        start_time = time.perf_counter()

        try:
            response = self._create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
                **{self._token_param: max_tokens},
            )
            duration = round(time.perf_counter() - start_time, 2)
            tin, tout = self._token_counts(response)
            print(f"[DeepInfra] ✅ DONE  | Duration: {duration}s | Tokens: {tin}/{tout}")

            return LLMResponse(
                text=self._text(response),
                model=model,
                provider=self._provider_label,
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=_deepinfra_cost(model, tin, tout),
            )
        except Exception as exc:
            duration = round(time.perf_counter() - start_time, 2)
            print(f"[DeepInfra] ❌ FAILED | Duration: {duration}s | Error: {exc}")
            raise

    def complete_streaming(
        self,
        prompt: str,
        *,
        system: str = "",
        image_b64: str | list[str] = "",
        media_type: str = "image/jpeg",
        max_tokens: int = 32000,
        force_json: bool = False,
        response_schema: dict | None = None,
        tier: str = "smart",
    ) -> LLMResponse:
        model = self._model_name(tier)
        print(f"[DeepInfra] 🚀 START | Model: {model} | Tier: {tier}")
        start_time = time.perf_counter()

        try:
            messages: list[dict] = []
            if system:
                messages.append({"role": "system", "content": system})

            images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
            if images and images[0]:
                content: list[dict] = [{"type": "text", "text": prompt}]
                for img in images:
                    content.append({
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{media_type};base64,{img}",
                        },
                    })
                messages.append({"role": "user", "content": content})
            else:
                messages.append({"role": "user", "content": prompt})

            kwargs: dict = {
                "model": model,
                "messages": messages,
                "temperature": self._temperature,
                self._token_param: max_tokens,
            }

            response = self._create(**kwargs)
            duration = round(time.perf_counter() - start_time, 2)
            tin, tout = self._token_counts(response)
            print(f"[DeepInfra] ✅ DONE  | Duration: {duration}s | Tokens: {tin}/{tout}")

            return LLMResponse(
                text=self._text(response),
                model=model,
                provider=self._provider_label,
                input_tokens=tin,
                output_tokens=tout,
                cost_usd=_deepinfra_cost(model, tin, tout),
            )
        except Exception as exc:
            duration = round(time.perf_counter() - start_time, 2)
            print(f"[DeepInfra] ❌ FAILED | Duration: {duration}s | Error: {exc}")
            raise

    def complete_with_image(
        self,
        prompt: str,
        image_b64: str | list[str],
        media_type: str,
        *,
        max_tokens: int = 32000,
        force_json: bool = False,
        response_schema: dict | None = None,
        tier: str = "fast",
    ) -> LLMResponse:
        return self.complete_streaming(
            prompt,
            image_b64=image_b64,
            media_type=media_type,
            max_tokens=max_tokens,
            force_json=force_json,
            response_schema=response_schema,
            tier=tier,
        )
