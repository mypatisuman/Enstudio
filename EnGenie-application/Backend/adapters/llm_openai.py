"""
adapters/llm_openai.py — OpenAI (public API) provider for EngineeringStudio.

Uses the openai Python SDK's plain OpenAI client — one shared public
endpoint, so this only ever needs an API key + model name.
Implements: complete(), complete_with_image(), complete_streaming()

Also doubles as the adapter for any named custom provider preset (Grok,
DeepSeek, Mistral, Groq, OpenRouter, Together...) — see adapters/llm_presets.py
— since those all expose the same OpenAI-compatible chat/completions shape.
Passing `base_url` points the SDK at that provider instead of api.openai.com.
"""

from __future__ import annotations

from adapters.llm_provider import LLMProvider, LLMResponse

# Cost per million tokens (input / output) — GPT-4o/GPT-5 family.
_COST: dict[str, tuple[float, float]] = {
    'gpt-4o':        (2.50, 10.00),
    'gpt-4o-mini':   (0.15,  0.60),
    'gpt-4.1':       (2.00,  8.00),
    'gpt-4.1-mini':  (0.40,  1.60),
    'gpt-5':         (5.00, 20.00),
    'gpt-5.4':       (5.00, 20.00),
    'gpt-5.5':       (5.00, 20.00),   # ponytail: same rate as 5.4 assumed — confirm actual pricing when available
}


def _cost(model: str, tin: int, tout: int) -> float:
    rates = _COST.get(model, (5.00, 20.00))
    return round((tin * rates[0] + tout * rates[1]) / 1_000_000, 6)


class OpenAIProvider(LLMProvider):

    @property
    def provider_name(self) -> str:   # type: ignore[override]
        """Per-instance: this class also backs every 'custom:<id>' preset
        (adapters/llm_presets.py), so the vision lookup must see the real
        label rather than a hardcoded 'openai'."""
        return getattr(self, '_provider_label', 'openai')

    """Public OpenAI API provider using the openai Python SDK.

    Also used for any custom OpenAI-compatible preset (Grok, DeepSeek,
    Mistral, Groq, OpenRouter, Together...) by passing `base_url` +
    `provider_label` — see adapters/llm_factory.py's 'custom:' branch.
    """

    def __init__(self, api_key: str = '', model: str = 'gpt-5.5',
                 model_fast: str | None = None,
                 temperature: float = 0.0,
                 base_url: str | None = None,
                 provider_label: str = 'openai') -> None:
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key, base_url=base_url) if base_url else OpenAI(api_key=api_key)
        self._model_smart = model
        self._model_fast  = model_fast or model
        self._temperature = temperature
        self._provider_label = provider_label
        # Real OpenAI's newest models (gpt-5.x) require the renamed
        # `max_completion_tokens`; every third-party OpenAI-compatible preset
        # (Grok, DeepSeek, Mistral, Groq, OpenRouter, Together) only supports
        # the older `max_tokens` — DeepSeek/Mistral/Together reject or ignore
        # the new name entirely. base_url set = a preset, so use the one
        # every provider actually accepts.
        self._token_param = 'max_tokens' if base_url else 'max_completion_tokens'
        # Some models (e.g. gpt-5.5) reject any explicit temperature and only
        # accept the default — remembered per-model after the first rejection
        # so we don't retry every call.
        self._no_custom_temperature: set[str] = set()

    def _create(self, **kwargs):
        """chat.completions.create with automatic fallback for models that
        reject an explicit temperature value (only default supported)."""
        model: str = kwargs.get('model', '')
        if model in self._no_custom_temperature:
            kwargs.pop('temperature', None)
            return self._client.chat.completions.create(**kwargs)
        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as exc:
            if 'temperature' in str(exc) and 'does not support' in str(exc):
                self._no_custom_temperature.add(model)
                kwargs.pop('temperature', None)
                return self._client.chat.completions.create(**kwargs)
            raise

    def _model_name(self, tier: str) -> str:
        return self._model_smart if tier == 'smart' else self._model_fast

    def _token_counts(self, response) -> tuple[int, int]:
        usage = getattr(response, 'usage', None)
        if not usage:
            return 0, 0
        return getattr(usage, 'prompt_tokens', 0), getattr(usage, 'completion_tokens', 0)

    def _text(self, response) -> str:
        try:
            return response.choices[0].message.content or ''
        except (IndexError, AttributeError):
            return ''

    # ── Text-only completion ──────────────────────────────────────────────────

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        model = self._model_name(tier)
        response = self._create(
            model=model,
            messages=[{'role': 'user', 'content': prompt}],
            temperature=self._temperature,
            **{self._token_param: max_tokens},
        )
        tin, tout = self._token_counts(response)
        return LLMResponse(
            text=self._text(response), model=model, provider=self._provider_label,
            input_tokens=tin, output_tokens=tout,
            cost_usd=_cost(model, tin, tout),
        )

    # ── Vision completion (image + text) ─────────────────────────────────────

    def complete_with_image(self, prompt: str, image_b64: str | list[str],
                            media_type: str, *, max_tokens: int = 32000,
                            force_json: bool = False,
                            response_schema: dict | None = None,
                            tier: str = 'fast') -> LLMResponse:
        return self.complete_streaming(
            prompt, image_b64=image_b64, media_type=media_type,
            max_tokens=max_tokens, force_json=force_json,
            response_schema=response_schema, tier=tier,
        )

    # ── Streaming-compatible completion (main vision pass) ────────────────────

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000, force_json: bool = False,
                           response_schema: dict | None = None,
                           tier: str = 'smart') -> LLMResponse:
        model = self._model_name(tier)

        messages: list[dict] = []
        if system:
            messages.append({'role': 'system', 'content': system})

        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        if images and images[0]:
            content: list[dict] = [{'type': 'text', 'text': prompt}]
            for img in images:
                content.append({'type': 'image_url', 'image_url': {
                    'url': f'data:{media_type};base64,{img}',
                    # No 'detail' key: gpt-5.x processes each image natively at full
                    # resolution without the 512px tiling that 'detail: high' triggers.
                }})
            messages.append({'role': 'user', 'content': content})
        else:
            messages.append({'role': 'user', 'content': prompt})

        kwargs: dict = dict(
            model=model,
            messages=messages,
            temperature=self._temperature,
            **{self._token_param: max_tokens},
        )
        # For vision calls we never set response_format — let the model reason
        # freely and output JSON in ```json``` fences (prompts instruct this).

        response = self._create(**kwargs)
        tin, tout = self._token_counts(response)
        return LLMResponse(
            text=self._text(response), model=model, provider=self._provider_label,
            input_tokens=tin, output_tokens=tout,
            cost_usd=_cost(model, tin, tout),
        )
