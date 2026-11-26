"""
adapters/llm_ollama.py — Ollama local LLM provider for EngineeringStudio.

Connects to the Ollama server on this machine (default http://localhost:11434,
OLLAMA_BASE_URL to change the port). The model installed here is
qwen2.5vl:3b, which reads images; vision calls need such a model.

OLLAMA_MODEL picks the model for both tiers. OLLAMA_TIMEOUT_S bounds one call:
on a laptop CPU with no GPU, one 1500 px drawing tile took 8-9 minutes.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from adapters.llm_provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_URL = 'http://localhost:11434'
DEFAULT_MODEL = 'qwen2.5vl:3b'
TIMEOUT_S = float(os.getenv('OLLAMA_TIMEOUT_S', '900'))


# Model-name substrings for known vision-capable Ollama families. Matched
# case-insensitively against the tag before the ':' (e.g. 'llava:13b' ->
# 'llava'). Deliberately a substring allowlist, not a full model registry —
# Ollama tags proliferate faster than this list could track exactly, but
# every genuinely multimodal family ships under one of these names.
_OLLAMA_VISION_FAMILIES = (
    'llava', 'moondream', 'bakllava', 'llama3.2-vision', 'llama-3.2-vision',
    'qwen2-vl', 'qwen2.5-vl', 'minicpm-v', 'pixtral', 'llava-llama3',
    'llava-phi3', 'granite3.2-vision',
    # Ollama's own tags drop the hyphen: qwen2.5vl:3b (installed here), qwen3-vl / qwen3vl
    'qwen2.5vl', 'qwen2vl', 'qwen3-vl', 'qwen3vl',
)


def _model_supports_vision(model_name: str) -> bool:
    name = (model_name or '').lower()
    return any(fam in name for fam in _OLLAMA_VISION_FAMILIES)


class OllamaProvider(LLMProvider):
    """Ollama provider using the /api/chat HTTP endpoint."""

    def __init__(self, base_url: str = DEFAULT_LOCAL_URL,
                 model_fast: str | None = None,
                 model_smart: str | None = None) -> None:
        self._base = base_url.rstrip('/')
        self._model_fast  = model_fast  or DEFAULT_MODEL
        self._model_smart = model_smart or DEFAULT_MODEL

    def _model(self, tier: str) -> str:
        return self._model_smart if tier == 'smart' else self._model_fast

    def supports_vision(self, tier: str = 'fast') -> bool:
        """Name-pattern check against _OLLAMA_VISION_FAMILIES — the Ollama
        API itself exposes no capability metadata short of a full /api/show
        call per model, so this stays a cheap local check rather than a
        network round-trip. False means "assume text-only"; a genuinely
        vision-capable model with an unrecognised tag name will read as
        unsupported here — update _OLLAMA_VISION_FAMILIES rather than
        bypassing this check if that happens."""
        return _model_supports_vision(self._model(tier))

    def _chat(self, model: str, messages: list, max_tokens: int,
              json_format: str | dict | None = None) -> str:
        body = {
            'model': model,
            'stream': False,
            'options': {'num_predict': max_tokens},
            'messages': messages,
        }
        if json_format:
            body['format'] = json_format       # "json", or a JSON schema the reply must follow
        payload = json.dumps(body).encode()
        req = urllib.request.Request(
            f'{self._base}/api/chat',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            data = json.loads(r.read())
        return (data.get('message') or {}).get('content', '')

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        model = self._model(tier)
        text = self._chat(model, [{'role': 'user', 'content': prompt}], max_tokens)
        return LLMResponse(text=text, model=model, provider='ollama')

    def complete_with_image(self, prompt: str, image_b64: str | list[str],
                            media_type: str, *, max_tokens: int = 32000,
                            force_json: bool = False, tier: str = 'fast') -> LLMResponse:
        model = self._model(tier)
        # Ollama vision: pass image(s) in the images list
        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        messages = [{
            'role': 'user',
            'content': prompt,
            'images': images,
        }]
        text = self._chat(model, messages, max_tokens, 'json' if force_json else None)
        return LLMResponse(text=text, model=model, provider='ollama')

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000, force_json: bool = False,
                           response_schema: dict | None = None,
                           tier: str = 'smart') -> LLMResponse:
        model = self._model(tier)
        messages = []
        if system:
            messages.append({'role': 'system', 'content': system})
        msg: dict = {'role': 'user', 'content': prompt}
        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        if images and images[0]:
            msg['images'] = images
        messages.append(msg)
        text = self._chat(model, messages, max_tokens,
                          response_schema or ('json' if force_json else None))
        return LLMResponse(text=text, model=model, provider='ollama')
