"""
adapters/llm_presets.py — named presets for third-party OpenAI-compatible
LLM providers (Grok, DeepSeek, Mistral, Groq, OpenRouter, Together...).

Each preset just supplies a base_url + default model; the actual request
logic is the existing OpenAIProvider (adapters/llm_openai.py) pointed at a
different base_url — these APIs all speak the same chat/completions shape.
"""

from __future__ import annotations

CUSTOM_PROVIDER_PRESETS: dict[str, dict[str, str]] = {
    'grok': {
        'label':         'Grok (xAI)',
        'base_url':      'https://api.x.ai/v1',
        'default_model': 'grok-4',
    },
    'deepseek': {
        'label':         'DeepSeek',
        'base_url':      'https://api.deepseek.com/v1',
        'default_model': 'deepseek-chat',
    },
    'mistral': {
        'label':         'Mistral AI',
        'base_url':      'https://api.mistral.ai/v1',
        'default_model': 'mistral-large-latest',
    },
    'groq': {
        'label':         'Groq',
        'base_url':      'https://api.groq.com/openai/v1',
        'default_model': 'llama-3.3-70b-versatile',
    },
    'openrouter': {
        'label':         'OpenRouter',
        'base_url':      'https://openrouter.ai/api/v1',
        'default_model': 'openai/gpt-4o',
    },
    'together': {
        'label':         'Together AI',
        'base_url':      'https://api.together.xyz/v1',
        'default_model': 'meta-llama/Llama-3.3-70B-Instruct-Turbo',
    },
    'deepinfra': {
        'label':         'DeepInfra (Gemma / Open Models)',
        'base_url':      'https://api.deepinfra.com/v1/openai',
        'default_model': 'google/gemma-4-31B-it-turbo',
    },
}
