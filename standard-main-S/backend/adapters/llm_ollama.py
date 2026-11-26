"""
adapters/llm_ollama.py — Ollama local LLM provider for EngineeringStudio.

Connects to a local Ollama instance (default http://localhost:11434).
Vision calls require a model with image support (e.g. llava, moondream).

Host selection (get_active_ollama_base_url): Ollama is the ONE documented
exception to this app's "config is DB/UI-only, never env vars" rule (see
adapters/config.py's module docstring). Provider/key/model choices for
every other provider stay UI-only by design; Ollama additionally honors
OLLAMA_BASE_URL / OLLAMA_FALLBACK_URL from the environment (.env), with
a live reachability probe and automatic fallback — e.g. a primary host
on a Mac Mini that isn't always powered on, falling back to a local
instance. This exists specifically because local-network Ollama hosts
come and go in a way a hosted API key never does.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

from adapters.llm_provider import LLMProvider, LLMResponse

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_URL = 'http://localhost:11434'


def _is_host_reachable(base_url: str, timeout: float = 1.5) -> bool:
    """Quick GET /api/tags probe — cheap reachability + "is this really
    an Ollama server" check. Any failure (refused, timeout, DNS, non-200)
    just means "not reachable"; never raises."""
    try:
        url = base_url.rstrip('/')
        if url.endswith('/v1'):
            url = url[:-3]
        req = urllib.request.Request(
            f'{url}/api/tags', headers={'User-Agent': 'studio-ollama-probe'})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception as e:
        logger.debug('[Ollama Probe] %s unreachable: %s', base_url, e)
        return False


def get_active_ollama_base_url(*, timeout: float = 1.5) -> str:
    """Primary-host-with-fallback selector, read from the environment:

        OLLAMA_BASE_URL      primary host (e.g. a Mac Mini on the LAN)
        OLLAMA_FALLBACK_URL  fallback host, default http://localhost:11434

    Probes the primary first; if unreachable, probes the fallback; if
    neither responds, returns the primary (or fallback) unprobed so the
    caller still gets a concrete URL and a clear connection-refused error
    downstream rather than this function raising.
    """
    primary = os.getenv('OLLAMA_BASE_URL', '').strip()
    fallback = os.getenv('OLLAMA_FALLBACK_URL', DEFAULT_LOCAL_URL).strip()

    if primary and _is_host_reachable(primary, timeout=timeout):
        logger.info('[Ollama Selector] primary host responding: %s', primary)
        return primary

    if fallback and fallback != primary and \
            _is_host_reachable(fallback, timeout=timeout):
        logger.warning('[Ollama Selector] primary %r unreachable — '
                       'falling back to %s', primary, fallback)
        return fallback

    chosen = primary or fallback or DEFAULT_LOCAL_URL
    logger.info('[Ollama Selector] neither host responded to probe; '
               'using %s unprobed', chosen)
    return chosen


# Model-name substrings for known vision-capable Ollama families. Matched
# case-insensitively against the tag before the ':' (e.g. 'llava:13b' ->
# 'llava'). Deliberately a substring allowlist, not a full model registry —
# Ollama tags proliferate faster than this list could track exactly, but
# every genuinely multimodal family ships under one of these names.
_OLLAMA_VISION_FAMILIES = (
    'llava', 'moondream', 'bakllava', 'llama3.2-vision', 'llama-3.2-vision',
    'qwen2-vl', 'qwen2.5-vl', 'minicpm-v', 'pixtral', 'llava-llama3',
    'llava-phi3', 'granite3.2-vision',
)


def _model_supports_vision(model_name: str) -> bool:
    name = (model_name or '').lower()
    return any(fam in name for fam in _OLLAMA_VISION_FAMILIES)


class OllamaProvider(LLMProvider):
    """Ollama provider using the /api/chat HTTP endpoint."""

    def __init__(self, base_url: str = 'http://localhost:11434',
                 model_fast: str | None = None,
                 model_smart: str | None = None) -> None:
        self._base = base_url.rstrip('/')
        self._model_fast  = model_fast  or 'qwen2.5:3b-instruct'
        self._model_smart = model_smart or 'llama3.1:70b'

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

    def _chat(self, model: str, messages: list, max_tokens: int) -> str:
        payload = json.dumps({
            'model': model,
            'stream': False,
            'options': {'num_predict': max_tokens},
            'messages': messages,
        }).encode()
        req = urllib.request.Request(
            f'{self._base}/api/chat',
            data=payload,
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with urllib.request.urlopen(req, timeout=300) as r:
            data = json.loads(r.read())
        return (data.get('message') or {}).get('content', '')

    def complete(self, prompt: str, *, max_tokens: int = 8000,
                 tier: str = 'fast') -> LLMResponse:
        model = self._model(tier)
        text = self._chat(model, [{'role': 'user', 'content': prompt}], max_tokens)
        return LLMResponse(text=text, model=model, provider='ollama')

    def complete_with_image(self, prompt: str, image_b64: str | list[str],
                            media_type: str, *, max_tokens: int = 32000,
                            tier: str = 'fast') -> LLMResponse:
        model = self._model(tier)
        # Ollama vision: pass image(s) in the images list
        images = [image_b64] if isinstance(image_b64, str) else list(image_b64)
        messages = [{
            'role': 'user',
            'content': prompt,
            'images': images,
        }]
        text = self._chat(model, messages, max_tokens)
        return LLMResponse(text=text, model=model, provider='ollama')

    def complete_streaming(self, prompt: str, *, system: str = '',
                           image_b64: str | list[str] = '', media_type: str = 'image/jpeg',
                           max_tokens: int = 32000,
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
        text = self._chat(model, messages, max_tokens)
        return LLMResponse(text=text, model=model, provider='ollama')
