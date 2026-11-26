"""
controllers/settings_controller.py — settings, usage logging, and layout-rules endpoints

Extracted from main.py (Phase 8): request parsing, validation, service/repo
calls, and jsonify()/response construction for these routes -- moved
verbatim into per-function controller bodies. Flask route decorators,
function signatures, and endpoint names all remain in main.py unchanged;
each route body is now a one-line delegate to the matching function here.

Main.py-level names used by these bodies (module-level singletons like
PROJECTS_DIR/HUB/cache_store/llm/skill_registry, and the thin repository/
service wrapper functions established in Phases 2-7) are pulled in via a
function-local `import main as _m` -- mirroring the pre-existing lazy-import
pattern already used elsewhere in this codebase (api/detect.py, extract_cli.py)
to reach main.py without a module-level circular import (main.py imports
this controller module at startup).
"""
from __future__ import annotations

from flask_compat import jsonify, request
import datetime

from adapters.llm_factory import get_provider

def get_layout_rules():
    import main as _m
    _apply_convention_overrides = _m._apply_convention_overrides
    _load_layout_rules = _m._load_layout_rules
    """Return merged layout rules: skill-file defaults + project company overrides."""
    pid = request.args.get('pid', '')
    rules = _load_layout_rules()
    if pid:
        rules = _apply_convention_overrides(rules, pid)
    return jsonify(rules)


def get_settings():
    from adapters.config import public_config
    return jsonify(public_config())


def save_settings():
    import main as _m
    from adapters.config import save_config
    updates = request.get_json(force=True, silent=True) or {}
    try:
        save_config(updates)
        _m.llm = get_provider()  # mutate main.py's shared provider singleton
        return jsonify({'ok': True})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


def test_llm_connection():
    from adapters.config import save_config, load_config, SENTINEL
    data = request.get_json(force=True, silent=True) or {}
    # apply posted values temporarily (don't persist yet)
    try:
        from adapters.llm_factory import get_provider as _gp
        from adapters.config import load_config as _lc
        cfg = _lc()
        for k, v in data.items():
            if k == 'anthropic_api_key' and v == SENTINEL:
                continue
            cfg[k] = v
        provider_name = cfg.get('llm_provider', 'anthropic')
        if provider_name == 'anthropic':
            from adapters.llm_anthropic import AnthropicProvider
            prov = AnthropicProvider(
                api_key=cfg.get('anthropic_api_key', ''),
                model_fast=cfg.get('anthropic_model_fast'),
                model_smart=cfg.get('anthropic_model_smart'),
            )
        elif provider_name == 'gemini':
            from adapters.llm_gemini import GeminiProvider
            prov = GeminiProvider(
                api_key=cfg.get('gemini_api_key', ''),
                model_fast=cfg.get('gemini_model_fast'),
                model_smart=cfg.get('gemini_model_smart'),
            )
        elif provider_name == 'openai':
            from adapters.llm_openai import OpenAIProvider
            prov = OpenAIProvider(
                api_key=cfg.get('openai_api_key', ''),
                model=cfg.get('openai_model_smart', 'gpt-5.5'),
            )
        elif provider_name == 'ollama':
            from adapters.llm_ollama import OllamaProvider
            prov = OllamaProvider(
                base_url=cfg.get('ollama_url', 'http://localhost:11434'),
                model_fast=cfg.get('ollama_model_fast'),
                model_smart=cfg.get('ollama_model_smart'),
            )
        elif provider_name == 'deepinfra':
            from adapters.llm_deepinfra import DeepInfraProvider
            prov = DeepInfraProvider(
                api_key=cfg.get('deepinfra_api_key', ''),
                model=cfg.get('deepinfra_model_smart'),
                model_fast=cfg.get('deepinfra_model_fast'),
            )
        elif provider_name.startswith('custom:'):
            from adapters.llm_presets import CUSTOM_PROVIDER_PRESETS
            preset_id = provider_name.split(':', 1)[1]
            preset = CUSTOM_PROVIDER_PRESETS.get(preset_id)
            if preset is None:
                return jsonify({'ok': False, 'error': f"Unknown custom provider preset '{preset_id}'"}), 400
            if preset_id == 'deepinfra':
                from adapters.llm_deepinfra import DeepInfraProvider
                prov = DeepInfraProvider(
                    api_key=cfg.get('custom_deepinfra_api_key') or cfg.get('deepinfra_api_key', ''),
                    model=cfg.get('custom_deepinfra_model') or cfg.get('deepinfra_model_smart') or preset['default_model'],
                    model_fast=cfg.get('deepinfra_model_fast'),
                    base_url=preset['base_url'],
                    provider_label=provider_name,
                )
            else:
                from adapters.llm_openai import OpenAIProvider
                prov = OpenAIProvider(
                    api_key=cfg.get(f'custom_{preset_id}_api_key', ''),
                    model=cfg.get(f'custom_{preset_id}_model') or preset['default_model'],
                    base_url=preset['base_url'],
                    provider_label=provider_name,
                )
        else:
            return jsonify({'ok': False, 'error': f"Unknown provider: {provider_name}"}), 400

        resp = prov.complete('Reply with the single word: OK', max_tokens=10, tier='fast')
        return jsonify({'ok': True, 'model': resp.model, 'reply': resp.text})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 400


def get_usage():
    import main as _m
    _load_usage = _m._load_usage
    return jsonify(_load_usage())


def log_usage():
    import main as _m
    _append_usage = _m._append_usage
    record = request.get_json(force=True, silent=True) or {}
    record.setdefault('timestamp', datetime.datetime.utcnow().isoformat())
    _append_usage(record)
    return jsonify({'ok': True})


def clear_usage():
    import main as _m
    _USAGE_FILE = _m._USAGE_FILE
    _USAGE_FILE.write_text('[]', encoding='utf-8')
    return jsonify({'ok': True})
