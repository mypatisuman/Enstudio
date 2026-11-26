"""
adapters/llm_factory.py — LLM provider factory for EngineeringStudio.

Usage:
    from adapters.llm_factory import get_provider
    llm = get_provider()                    # reads LLM_PROVIDER env / studio_config.json
    llm = get_provider(name='ollama')       # explicit override
    resp = llm.complete(prompt, max_tokens=4096, tier='fast')

Provider selection ('llm_provider' in the settings table — chosen from the
frontend Settings screen only, never an env var):
    anthropic     →  AnthropicProvider   (default)
    gemini        →  GeminiProvider
    openai        →  OpenAIProvider
    ollama        →  OllamaProvider
    custom:<id>   →  OpenAIProvider pointed at a named preset's base_url
                      (Grok, DeepSeek, Mistral, Groq, OpenRouter, Together...
                      see adapters/llm_presets.py)
"""

from __future__ import annotations

from adapters.config import load_config
from adapters.llm_provider import LLMProvider


def get_provider(name: str | None = None) -> LLMProvider:
    """Instantiate and return the configured LLM provider.

    Args:
        name: Override the provider name ('anthropic', 'ollama').
              If None, reads from config/env.
    """
    cfg  = load_config()
    name = (name or cfg.get('llm_provider', 'anthropic')).lower().strip()

    if name == 'anthropic':
        from adapters.llm_anthropic import AnthropicProvider
        return AnthropicProvider(
            api_key=cfg.get('anthropic_api_key', ''),
            model_fast=cfg.get('anthropic_model_fast'),
            model_smart=cfg.get('anthropic_model_smart'),
            temperature=0.0,
        )

    if name == 'gemini':
        from adapters.llm_gemini import GeminiProvider
        return GeminiProvider(
            api_key=cfg.get('gemini_api_key', ''),
            model_fast=cfg.get('gemini_model_fast'),
            model_smart=cfg.get('gemini_model_smart'),
            temperature=0.0,
        )

    if name == 'openai':
        from adapters.llm_openai import OpenAIProvider
        return OpenAIProvider(
            api_key=cfg.get('openai_api_key', ''),
            model=cfg.get('openai_model_smart', 'gpt-5.5'),
        )

    if name == 'ollama':
        # Ollama is the ONE env-var exception (see adapters/config.py's
        # docstring): a local-network Ollama host genuinely comes and goes in a
        # way a hosted API key never does, so OLLAMA_BASE_URL /
        # OLLAMA_FALLBACK_URL / OLLAMA_MODEL are honoured here. This wiring was
        # documented in agents/README.md and covered by
        # tests/test_ollama_host_selection.py, but had never actually been
        # connected to the factory -- the saved setting always won and the env
        # vars did nothing.
        import os as _os
        from adapters.llm_ollama import OllamaProvider, get_active_ollama_base_url

        if (_os.getenv('OLLAMA_BASE_URL') or '').strip():
            # Env primary present: probe it, fall back per the selector.
            base_url = get_active_ollama_base_url()
        else:
            # No env primary: settings-table value, exactly as before.
            base_url = cfg.get('ollama_url') or 'http://localhost:11434'

        # Ollama models are one size class, so OLLAMA_MODEL overrides BOTH
        # tiers rather than only the fast one.
        env_model = (_os.getenv('OLLAMA_MODEL') or '').strip()
        return OllamaProvider(
            base_url=base_url,
            model_fast=env_model or cfg.get('ollama_model_fast'),
            model_smart=env_model or cfg.get('ollama_model_smart'),
        )

    if name == 'deepinfra':
        from adapters.llm_deepinfra import DeepInfraProvider
        return DeepInfraProvider(
            api_key=cfg.get('deepinfra_api_key', ''),
            model=cfg.get('deepinfra_model_smart'),
            model_fast=cfg.get('deepinfra_model_fast'),
            provider_label='deepinfra',
        )

    if name.startswith('custom:'):
        from adapters.llm_presets import CUSTOM_PROVIDER_PRESETS
        preset_id = name.split(':', 1)[1]
        preset = CUSTOM_PROVIDER_PRESETS.get(preset_id)
        if preset is None:
            raise ValueError(f"Unknown custom provider preset '{preset_id}'")
        if preset_id == 'deepinfra':
            from adapters.llm_deepinfra import DeepInfraProvider
            return DeepInfraProvider(
                api_key=cfg.get('custom_deepinfra_api_key') or cfg.get('deepinfra_api_key', ''),
                model=cfg.get('custom_deepinfra_model') or cfg.get('deepinfra_model_smart') or preset['default_model'],
                model_fast=cfg.get('deepinfra_model_fast'),
                base_url=preset['base_url'],
                provider_label=name,
            )
        from adapters.llm_openai import OpenAIProvider
        return OpenAIProvider(
            api_key=cfg.get(f'custom_{preset_id}_api_key', ''),
            model=cfg.get(f'custom_{preset_id}_model') or preset['default_model'],
            base_url=preset['base_url'],
            provider_label=name,
        )

    raise ValueError(
        f"Unknown LLM_PROVIDER '{name}'. Supported: anthropic, gemini, openai, ollama, deepinfra, custom:<preset id>"
    )
