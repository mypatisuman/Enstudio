"""
adapters/llm_gemini.py — Google Gemini provider for EngineeringStudio.

Uses the current google-genai SDK (pip: google-genai).
Implements: complete(), complete_with_image(), complete_streaming()

Notes for gemini-2.5-flash:
  - Safety settings relaxed to BLOCK_ONLY_HIGH so industrial P&ID content
    (chemicals, pressure, hazardous processes) is not blocked.
  - Thinking tokens tracked separately and added to cost at thinking rate.
  - Set GEMINI_THINKING_BUDGET=0 in .env to disable thinking (default).
    Set GEMINI_THINKING_BUDGET=-1 to let the model decide its own budget.
"""

from __future__ import annotations

import os
from adapters.llm_provider import LLMProvider, LLMResponse

# Cost per million tokens (input / output) at June 2026 pricing.
_COST: dict[str, tuple[float, float]] = {
    'gemini-2.0-flash':            (0.075,  0.30),
    'gemini-2.0-flash-lite':       (0.0375, 0.15),
    'gemini-2.5-flash':            (0.15,   0.60),
    'gemini-2.5-flash-lite':       (0.075,  0.30),
    'gemini-2.5-pro':              (1.25,  10.00),
    'gemini-1.5-pro':              (1.25,   5.00),
    'gemini-1.5-flash':            (0.075,  0.30),
    # Gemini 3.x — pricing TBD, using preview estimates
    'gemini-3-pro-preview':        (1.25,  10.00),
    'gemini-3-flash-preview':      (0.15,   0.60),
    'gemini-3.1-pro-preview':      (1.25,  10.00),
    'gemini-3.1-flash-lite-preview':(0.075, 0.30),
}

# Thinking token rate per million (billed separately for 2.5+ models)
_THINKING_COST_PER_M: dict[str, float] = {
    'gemini-2.5-flash':        3.50,
    'gemini-2.5-pro':          3.50,
    'gemini-3-pro-preview':    3.50,
    'gemini-3.1-pro-preview':  3.50,
}


def _cost(model: str, tin: int, tout: int, tthink: int = 0) -> float:
    rates = _COST.get(model, (0.075, 0.30))
    think_rate = _THINKING_COST_PER_M.get(model, 0.0)
    return round(
        (tin * rates[0] + tout * rates[1] + tthink * think_rate) / 1_000_000, 6
    )


def _token_counts(response) -> tuple[int, int, int]:
    """Return (input_tokens, output_tokens, thinking_tokens)."""
    meta = getattr(response, 'usage_metadata', None)
    if not meta:
        return 0, 0, 0
    tin    = getattr(meta, 'prompt_token_count',     0) or 0
    tout   = getattr(meta, 'candidates_token_count', 0) or 0
    tthink = getattr(meta, 'thoughts_token_count',   0) or 0
    return tin, tout, tthink


def _extract_text(response) -> str:
    """Safely pull text from a response; returns '' if blocked."""
    try:
        return response.text or ''
    except (ValueError, AttributeError):
        parts = []
        for cand in getattr(response, 'candidates', []):
            for part in getattr(getattr(cand, 'content', None), 'parts', []):
                t = getattr(part, 'text', None)
                if t:
                    parts.append(t)
        return ''.join(parts)


class GeminiProvider(LLMProvider):

    provider_name = 'gemini'

    """Google Gemini API provider using the google-genai Python SDK."""

    def __init__(self, api_key: str = '',
                 model_fast: str | None = None,
                 model_smart: str | None = None,
                 temperature: float = 0.0) -> None:
        from google import genai
        self._genai  = genai
        self._client = genai.Client(api_key=api_key or '')
        self._model_fast  = model_fast  or 'gemini-2.5-flash-lite'
        self._model_smart = model_smart or 'gemini-2.5-flash'
        self._temperature = temperature

    def _model_name(self, tier: str) -> str:
        return self._model_smart if tier == 'smart' else self._model_fast

    def _build_config(self, model_name: str, max_tokens: int,
                      force_json: bool = False, response_schema: dict | None = None):
        from google.genai import types

        safety = [
            types.SafetySetting(category='HARM_CATEGORY_DANGEROUS_CONTENT', threshold='BLOCK_ONLY_HIGH'),
            types.SafetySetting(category='HARM_CATEGORY_HARASSMENT',        threshold='BLOCK_ONLY_HIGH'),
            types.SafetySetting(category='HARM_CATEGORY_HATE_SPEECH',       threshold='BLOCK_ONLY_HIGH'),
            types.SafetySetting(category='HARM_CATEGORY_SEXUALLY_EXPLICIT', threshold='BLOCK_ONLY_HIGH'),
        ]

        cfg_kwargs: dict = dict(
            max_output_tokens=max_tokens,
            temperature=self._temperature,
            top_p=1,
            top_k=1,
            safety_settings=safety,
        )

        if response_schema:
            # Structured Outputs: token-level constrained decoding — the model
            # physically cannot produce output that violates this schema.
            # Implies application/json mime type automatically.
            cfg_kwargs['response_mime_type'] = 'application/json'
            cfg_kwargs['response_schema'] = response_schema
        elif force_json:
            # No schema provided — still force raw JSON with no markdown fences.
            cfg_kwargs['response_mime_type'] = 'application/json'

        # Thinking budget for 2.5+ and 3.x models.
        # Set GEMINI_THINKING_BUDGET=-1 in .env to let the model choose its own budget.
        # Note: thinking + response_schema conflict — when thinking is on, drop the schema
        # and rely on force_json (mime type only) for output format.
        _thinking_models = ('gemini-2.5', 'gemini-3')
        if any(t in model_name for t in _thinking_models):
            try:
                budget = int(os.environ.get('GEMINI_THINKING_BUDGET', '-1'))
            except ValueError:
                budget = -1
            cfg_kwargs['thinking_config'] = types.ThinkingConfig(thinking_budget=budget)

        return types.GenerateContentConfig(**cfg_kwargs)

    # ── Text-only completion ──────────────────────────────────────────────────

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        model_name = self._model_name(tier)
        response = self._client.models.generate_content(
            model=model_name,
            contents=prompt,
            config=self._build_config(model_name, max_tokens),
        )
        text = _extract_text(response)
        tin, tout, tthink = _token_counts(response)
        return LLMResponse(
            text=text, model=model_name, provider='gemini',
            input_tokens=tin, output_tokens=tout + tthink,
            cost_usd=_cost(model_name, tin, tout, tthink),
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

    # ── Streaming-compatible completion (Pass 1 — large context, image) ──────

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000, force_json: bool = False,
                           response_schema: dict | None = None,
                           tier: str = 'smart') -> LLMResponse:
        import base64, io
        from PIL import Image as _Image

        model_name = self._model_name(tier)
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt

        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        if images and images[0]:
            contents = [full_prompt] + [
                _Image.open(io.BytesIO(base64.b64decode(img))) for img in images
            ]
        else:
            contents = full_prompt

        response = self._client.models.generate_content(
            model=model_name,
            contents=contents,
            config=self._build_config(model_name, max_tokens,
                                      force_json=force_json,
                                      response_schema=response_schema),
        )
        text = _extract_text(response)
        tin, tout, tthink = _token_counts(response)
        return LLMResponse(
            text=text, model=model_name, provider='gemini',
            input_tokens=tin, output_tokens=tout + tthink,
            cost_usd=_cost(model_name, tin, tout, tthink),
        )
