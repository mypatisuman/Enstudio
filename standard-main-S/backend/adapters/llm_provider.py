"""
adapters/llm_provider.py — Shared response type and provider base class.
"""

from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class LLMResponse:
    """Returned by every provider method. Attributes inspected by CacheStore."""
    text:          str
    model:         str   = ''
    provider:      str   = ''
    input_tokens:  int   = 0
    output_tokens: int   = 0
    cost_usd:      float = 0.0
    #: Prompt-cache accounting (Anthropic). `input_tokens` stays the UNCACHED
    #: input only, as the API reports it; these two are billed separately.
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens:     int = 0


class LLMProvider:
    """Abstract base — subclass and implement all three methods."""

    #: Provider id used for the vision-capability lookup. Subclasses set
    #: this to 'anthropic' / 'gemini' / 'openai' / 'ollama' / 'custom:<id>'.
    provider_name: str = ''

    def supports_vision(self, tier: str = 'fast') -> bool:
        """True when this provider's model for `tier` accepts image input.

        Defined HERE, on the base class, so the guard in the three agentic
        detection services can never raise AttributeError on a provider
        that forgot to implement it — which is exactly what used to happen
        on Anthropic/Gemini/OpenAI, where only OllamaProvider had the
        method, leaving the whole vision-LLM detection pipeline dead on
        the default provider. See adapters/vision_capability.py.
        """
        from adapters.vision_capability import supports_vision_for
        model = ''
        # Providers spell the per-tier model accessor differently:
        # _model() on Anthropic/Ollama, _model_name() on Gemini/OpenAI.
        for attr in ('_model', '_model_name'):
            getter = getattr(self, attr, None)
            if callable(getter):
                try:
                    model = getter(tier) or ''
                except Exception:
                    model = ''
                if model:
                    break
        return supports_vision_for(self.provider_name, model)

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        raise NotImplementedError

    def complete_with_image(self, prompt: str, image_b64: str | list[str],
                            media_type: str, *, max_tokens: int = 32000,
                            tier: str = 'fast') -> LLMResponse:
        raise NotImplementedError

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000, force_json: bool = False,
                           response_schema: dict | None = None,
                           tier: str = 'smart') -> LLMResponse:
        """image_b64 may be a single base64 string or a list of them (e.g. tiles
        of one drawing) — each is sent as its own image in the same message."""
        raise NotImplementedError
