"""
adapters/config.py — Persistent LLM provider configuration for EngineeringStudio.

Storage: the `settings` key/value table in studio.db — the SAME database
the desktop app's Settings screen writes to (src-tauri/src/config/mod.rs's
save_config_key()). Both must point at one store for "set it in Settings,
it's used everywhere" to actually hold.

Every value here is chosen from the frontend Settings screen only. There is
deliberately no environment-variable fallback/override for any provider key,
model, or endpoint — if it isn't saved through the UI, it isn't configured.
"""

from __future__ import annotations

import json

from adapters.secrets import decrypt_secret, encrypt_secret, is_secret_key

# Sentinel value — posted as api_key when the UI doesn't want to overwrite it.
SENTINEL = '__unchanged__'

import os

_DEFAULTS: dict = {
    'llm_provider':                  os.getenv('LLM_PROVIDER', 'deepinfra'),
    'anthropic_api_key':             os.getenv('ANTHROPIC_API_KEY', ''),
    'anthropic_model_fast':          'claude-haiku-4-5-20251001',
    'anthropic_model_smart':         'claude-sonnet-4-6',
    'gemini_api_key':                os.getenv('GEMINI_API_KEY', ''),
    'gemini_model_fast':             'gemini-2.5-flash-lite',
    'gemini_model_smart':            'gemini-2.5-flash',
    'openai_api_key':                os.getenv('OPENAI_API_KEY', ''),
    'openai_model_smart':            'gpt-5.5',
    'deepinfra_api_key':             os.getenv('DEEPINFRA_API_KEY', ''),
    'deepinfra_model_fast':          os.getenv('DEEPINFRA_MODEL_FAST', 'Qwen/Qwen3-VL-30B-A3B-Instruct'),
    'deepinfra_model_smart':         os.getenv('DEEPINFRA_MODEL_SMART', 'Qwen/Qwen3-VL-30B-A3B-Instruct'),
    'ollama_url':                    os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434'),
    'ollama_model_fast':             'qwen2.5vl:3b',     # the model installed on this machine
    'ollama_model_smart':            'qwen2.5vl:3b',
    # JSON array of preset ids the user has added (see adapters/llm_presets.py)
    # — e.g. '["grok","deepseek"]'. Each preset's own key/model live under
    # 'custom_<id>_api_key' / 'custom_<id>_model', set dynamically.
    'custom_providers':              '[]',
}



def _settings_db():
    from adapters.db import get_db
    conn = get_db()
    conn.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    return conn


def load_config() -> dict:
    """Load config from the settings table, defaults filling in anything unset.

    API keys are stored encrypted (see adapters/secrets.py) and are decrypted
    here, so every caller — llm_factory, the extraction CLI — keeps receiving
    plaintext and needs no change. A key that cannot be decrypted (studio.db
    copied from another machine or another Windows user) is returned as empty
    rather than as ciphertext, which would otherwise be sent to the provider
    as if it were a real key.
    """
    cfg = dict(_DEFAULTS)
    conn = _settings_db()
    for row in conn.execute('SELECT key, value FROM settings'):
        key, value = row['key'], row['value']
        if is_secret_key(key) and value:
            try:
                value = decrypt_secret(value)
            except Exception as e:      # noqa: BLE001 — never leak the value itself
                print(f'[config] Cannot decrypt {key}: {e} — treating as unset')
                value = ''
        cfg[key] = value
    return cfg


def save_config(updates: dict) -> None:
    """Persist updates to the settings table. SENTINEL values are not written.

    API keys are encrypted before they touch the DB, in the same format the
    desktop app's save_config_key() writes.
    """
    conn = _settings_db()
    for k, v in updates.items():
        if k.endswith('_api_key') and v == SENTINEL:
            continue
        value = str(v)
        if is_secret_key(k):
            value = encrypt_secret(value)
        conn.execute(
            'INSERT INTO settings (key, value) VALUES (?, ?) '
            'ON CONFLICT(key) DO UPDATE SET value = excluded.value',
            (k, value),
        )


def public_config() -> dict:
    """Return config safe to send to the browser (API keys masked)."""
    cfg = load_config()
    for key_field in list(cfg):
        if key_field.endswith('_api_key'):
            if cfg.get(key_field, ''):
                cfg[key_field] = SENTINEL
                cfg[f'{key_field}_set'] = True
            else:
                cfg[f'{key_field}_set'] = False
    return cfg


def get_custom_providers() -> list[str]:
    """Preset ids the user has added (see adapters/llm_presets.py)."""
    try:
        return json.loads(load_config().get('custom_providers', '[]'))
    except (json.JSONDecodeError, TypeError):
        return []


def add_custom_provider(preset_id: str) -> None:
    ids = get_custom_providers()
    if preset_id not in ids:
        ids.append(preset_id)
        save_config({'custom_providers': json.dumps(ids)})


def remove_custom_provider(preset_id: str) -> None:
    ids = [i for i in get_custom_providers() if i != preset_id]
    save_config({'custom_providers': json.dumps(ids)})
