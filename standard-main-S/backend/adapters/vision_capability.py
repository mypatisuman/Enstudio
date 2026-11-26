"""
adapters/vision_capability.py — shared "can this model see an image?" table.

WHY THIS EXISTS
---------------
The three agentic detection services (services/llm_symbol_detection_service.py,
llm_text_detection_service.py, llm_line_detection_service.py) each call
`llm.supports_vision('fast')` before doing any tile work. That guard exists
because a text-only model pointed at an image does not necessarily fail —
Ollama in particular accepts an `images` array against a text-only model,
ignores it, and returns confident, entirely hallucinated detections.

Until this module existed, `supports_vision` was implemented ONLY on
OllamaProvider. Every other provider (Anthropic, Gemini, OpenAI and the
OpenAI-compatible custom presets) inherited nothing, so the guard raised
`AttributeError: 'AnthropicProvider' object has no attribute
'supports_vision'` — which meant the entire vision-LLM detection pipeline
was dead on the default provider. This module supplies one capability
table so every provider answers the question the same way.

POLICY
------
Hosted frontier APIs reject an image against a text-only model with an
explicit API error, so a wrong "True" there is a loud, debuggable failure.
A locally hosted model silently ignores the image, so a wrong "True" there
is a SILENT correctness failure. The tables below are therefore permissive
for hosted providers (unknown model name => assume vision, the API will
say otherwise) and strict for Ollama (unknown model name => assume
text-only, handled in adapters/llm_ollama.py).
"""

from __future__ import annotations

# Model-name fragments that are known to be TEXT-ONLY on an otherwise
# vision-capable hosted provider. Matched case-insensitively as substrings.
_TEXT_ONLY_FRAGMENTS: dict[str, tuple[str, ...]] = {
    'anthropic': (
        # Claude 1/2 era predates image input. Claude 3 and everything
        # after it (including every claude-*-4-*/5-* id) is multimodal.
        'claude-instant',
        'claude-1',
        'claude-2',
    ),
    'gemini': (
        # Embedding and text-only task models on the Gemini endpoint.
        'embedding',
        'aqa',
        'text-bison',
        'chat-bison',
    ),
    'openai': (
        # Pre-4o chat models, plus non-chat endpoints that share the id space.
        'gpt-3.5',
        'gpt-4-0314',
        'gpt-4-0613',
        'gpt-4-32k',
        'davinci',
        'babbage',
        'embedding',
        'whisper',
        'tts-',
        'moderation',
    ),
    'deepinfra': (
        # Known text-only open models on DeepInfra
        'gemma-2-',
        'gemma-1',
        'llama-3.1-',
        'llama-3.3-',
        'deepseek-',
        'mistral-',
        'qwen2.5-72b-instruct',
        'qwen2.5-32b-instruct',
        'qwen2.5-14b-instruct',
        'qwen2.5-7b-instruct',
    ),
}

# OpenAI-compatible third-party presets (adapters/llm_presets.py) served
# through OpenAIProvider. These are keyed by the provider_label prefix
# 'custom:<id>'. Listed here only where the preset's DEFAULT model is
# text-only; anything absent falls through to the permissive default.
_TEXT_ONLY_CUSTOM_PRESETS: tuple[str, ...] = (
    'deepseek',    # deepseek-chat is text-only
    'mistral',     # mistral-large-latest is text-only
)


def supports_vision_for(provider: str, model: str) -> bool:
    """True when `model` on `provider` accepts image input.

    Permissive by design for hosted providers: an unrecognised model name
    reads as vision-capable, because the provider's own API will return an
    explicit error if it is not — a loud failure, not a silent wrong answer.
    """
    prov = (provider or '').lower().strip()
    name = (model or '').lower().strip()

    if prov.startswith('custom:'):
        preset_id = prov.split(':', 1)[1]
        if preset_id in _TEXT_ONLY_CUSTOM_PRESETS:
            return False
        if preset_id == 'deepinfra':
            prov = 'deepinfra'
        else:
            prov = 'openai'

    for fragment in _TEXT_ONLY_FRAGMENTS.get(prov, ()):
        if fragment in name:
            return False
    return True
