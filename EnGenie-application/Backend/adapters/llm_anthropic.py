"""
adapters/llm_anthropic.py — Anthropic (Claude) provider for EngineeringStudio.

Implements: complete(), complete_with_image(), complete_streaming()
All return LLMResponse with .text, .model, .input_tokens, .output_tokens, .cost_usd.
"""

from __future__ import annotations

from adapters.llm_provider import LLMProvider, LLMResponse

# USD per million tokens (input, output), by model family. Matched by prefix so
# dated snapshot ids (claude-haiku-4-5-20251001) resolve to their family. The
# previous table priced Haiku 4.5 at $0.25/$1.25 and Opus 4.7 at $15/$75, so
# every usage and cost figure the app showed for those models was wrong.
_COST: tuple[tuple[str, tuple[float, float]], ...] = (
    ("claude-fable-5-1",  (10.00, 50.00)),
    ("claude-fable-5",    (10.00, 50.00)),
    ("claude-opus-5",     (5.00, 25.00)),
    ("claude-opus-4-8",   (5.00, 25.00)),
    ("claude-opus-4-7",   (5.00, 25.00)),
    ("claude-opus-4-6",   (5.00, 25.00)),
    ("claude-sonnet-5",   (2.00, 10.00)),
    ("claude-sonnet-4-6", (3.00, 15.00)),
    ("claude-haiku-4-5",  (1.00, 5.00)),
)
_DEFAULT_RATES = (3.00, 15.00)

#: Cache pricing multipliers on the base input rate (5-minute TTL).
_CACHE_WRITE_MULTIPLIER = 1.25
_CACHE_READ_MULTIPLIER = 0.10


def _rates(model: str) -> tuple[float, float]:
    for prefix, rates in _COST:
        if (model or "").startswith(prefix):
            return rates
    return _DEFAULT_RATES


def _cost(model: str, tin: int, tout: int, cache_write: int = 0, cache_read: int = 0) -> float:
    rin, rout = _rates(model)
    total = (tin * rin + tout * rout
             + cache_write * rin * _CACHE_WRITE_MULTIPLIER
             + cache_read * rin * _CACHE_READ_MULTIPLIER)
    return round(total / 1_000_000, 6)


#: Model families that still accept an assistant-prefill turn. Opus 4.6 and
#: later, Sonnet 4.6 and later, and every Fable/Mythos model reject prefill with
#: HTTP 400. The default smart tier (claude-sonnet-4-6) is one of them, so the
#: JSON-mode calls that used prefill on that tier -- LLM A symbol verification
#: and the line verification pass -- failed on the default configuration.
_PREFILL_FAMILIES = ("claude-3", "claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-4-5",
                     "claude-opus-4-1", "claude-opus-4-2", "claude-sonnet-4-2")

_JSON_ONLY_INSTRUCTION = (
    "Respond with only the JSON object: no markdown fences, no prose before or after it."
)


def _supports_prefill(model: str) -> bool:
    """Unknown or newer models get the instruction-based path, never prefill."""
    return (model or "").startswith(_PREFILL_FAMILIES)


class AnthropicProvider(LLMProvider):
    """Claude API provider using the anthropic Python SDK."""

    provider_name = 'anthropic'

    def __init__(self, api_key: str = '',
                 model_fast: str | None = None,
                 model_smart: str | None = None,
                 temperature: float = 0.0) -> None:
        import anthropic as _anthropic
        self._client = _anthropic.Anthropic(api_key=api_key or '')
        self._model_fast  = model_fast  or 'claude-haiku-4-5-20251001'
        self._model_smart = model_smart or 'claude-sonnet-4-6'
        self._temperature = temperature

    def _model(self, tier: str) -> str:
        return self._model_smart if tier == 'smart' else self._model_fast

    # ── Text-only completion ──────────────────────────────────────────────────

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        model = self._model(tier)
        resp = self._client.messages.create(
            model=model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=[{'role': 'user', 'content': prompt}],
        )
        text = resp.content[0].text if resp.content else ''
        tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
        return LLMResponse(
            text=text, model=model, provider='anthropic',
            input_tokens=tin, output_tokens=tout,
            cost_usd=_cost(model, tin, tout),
        )

    # ── Vision completion (image + text) ─────────────────────────────────────
    # Routes through complete_streaming because Anthropic requires streaming
    # for operations that may exceed 10 minutes (e.g. large P&ID pages).

    def complete_with_image(self, prompt: str, image_b64: str | list[str],
                            media_type: str, *, max_tokens: int = 32000,
                            force_json: bool = False,
                            tier: str = 'fast') -> LLMResponse:
        return self.complete_streaming(
            prompt,
            image_b64=image_b64,
            media_type=media_type,
            max_tokens=max_tokens,
            force_json=force_json,
            tier=tier,
        )

    # ── Streaming completion (Pass 1 — large context, image) ─────────────────

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000, force_json: bool = False,
                           response_schema: dict | None = None,
                           tier: str = 'smart',
                           thinking: bool = False,
                           thinking_budget: int = 8000) -> LLMResponse:
        # response_schema is used by Gemini only; Claude uses assistant prefill instead.
        model = self._model(tier)

        use_prefill = force_json and _supports_prefill(model)
        if force_json and not use_prefill:
            prompt = f"{prompt}\n\n{_JSON_ONLY_INSTRUCTION}"

        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        if images and images[0]:
            safe_type = media_type if media_type in (
                'image/jpeg', 'image/png', 'image/gif', 'image/webp'
            ) else 'image/jpeg'
            content = [
                {
                    'type': 'image',
                    'source': {
                        'type': 'base64',
                        'media_type': safe_type,
                        'data': img,
                    },
                }
                for img in images
            ]
            content.append({'type': 'text', 'text': prompt})
        else:
            content = prompt

        messages = [{'role': 'user', 'content': content}]
        if use_prefill:
            # Assistant prefill forces the model to continue from '{', guaranteeing
            # raw JSON output with no markdown fences or explanatory text.
            messages.append({'role': 'assistant', 'content': '{'})

        kwargs: dict = dict(
            model=model,
            max_tokens=max_tokens,
            temperature=self._temperature,
            messages=messages,
        )
        if system:
            # The system prompt is the stable prefix of these calls (skill
            # instructions, or a tile prompt identical for every tile), while
            # the image and per-call text follow it. Marking it cacheable lets
            # repeat calls in a burst read it at ~0.1x the input price. Prefixes
            # below the model's minimum (4096 tokens on Haiku 4.5, 1024 on
            # Sonnet 4.6) are simply not cached -- the API reports zero cache
            # tokens and bills normally, so this is safe on every model.
            kwargs['system'] = [{'type': 'text', 'text': system,
                                 'cache_control': {'type': 'ephemeral'}}]
        if thinking:
            # Extended thinking: Claude reasons in a hidden scratchpad before
            # answering. Significantly improves consistency on complex rule-following.
            # Requires temperature=1 (Anthropic requirement for thinking mode).
            kwargs['thinking'] = {'type': 'enabled', 'budget_tokens': thinking_budget}
            kwargs['temperature'] = 1  # required by API when thinking is enabled

        with self._client.messages.stream(**kwargs) as stream:
            msg  = stream.get_final_message()
            # When extended thinking is on, content has ThinkingBlock + TextBlock.
            # get_final_text() only returns TextBlock content — what we want.
            text = stream.get_final_text()

        # When assistant prefill is used the response continues from after '{',
        # so we must prepend it to reconstruct the complete JSON object.
        if use_prefill:
            text = '{' + text

        usage = msg.usage if msg else None
        tin  = usage.input_tokens  if usage else 0
        tout = usage.output_tokens if usage else len(text) // 4
        cache_write = int(getattr(usage, 'cache_creation_input_tokens', 0) or 0)
        cache_read = int(getattr(usage, 'cache_read_input_tokens', 0) or 0)
        return LLMResponse(
            text=text, model=model, provider='anthropic',
            input_tokens=tin, output_tokens=tout,
            cost_usd=_cost(model, tin, tout, cache_write, cache_read),
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
        )
