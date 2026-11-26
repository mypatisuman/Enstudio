"""Tests for the Ollama-only env-var host/model selection:
adapters/llm_ollama.get_active_ollama_base_url() and its wiring into
adapters/llm_factory.get_provider('ollama'). No real network access —
_is_host_reachable is monkeypatched.

Confirms the scoped nature of this exception: every OTHER provider
still reads settings-table-only, unaffected by any OLLAMA_* env var.
"""
import sys
from pathlib import Path

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

from adapters import llm_ollama as O  # noqa: E402


# ── get_active_ollama_base_url() ─────────────────────────────────────────────

def test_primary_reachable_wins(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.113:11434")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", "http://localhost:11434")
    monkeypatch.setattr(O, "_is_host_reachable",
                        lambda url, timeout=1.5: url == "http://192.168.0.113:11434")
    assert O.get_active_ollama_base_url() == "http://192.168.0.113:11434"


def test_primary_unreachable_falls_back(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.113:11434")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", "http://localhost:11434")
    monkeypatch.setattr(O, "_is_host_reachable",
                        lambda url, timeout=1.5: url == "http://localhost:11434")
    assert O.get_active_ollama_base_url() == "http://localhost:11434"


def test_neither_reachable_returns_primary_unprobed(monkeypatch):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.113:11434")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", "http://localhost:11434")
    monkeypatch.setattr(O, "_is_host_reachable", lambda url, timeout=1.5: False)
    assert O.get_active_ollama_base_url() == "http://192.168.0.113:11434"


def test_no_primary_set_uses_fallback_default(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_FALLBACK_URL", raising=False)
    monkeypatch.setattr(O, "_is_host_reachable", lambda url, timeout=1.5: False)
    assert O.get_active_ollama_base_url() == O.DEFAULT_LOCAL_URL


def test_no_primary_but_fallback_reachable(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", "http://localhost:11434")
    monkeypatch.setattr(O, "_is_host_reachable",
                        lambda url, timeout=1.5: url == "http://localhost:11434")
    assert O.get_active_ollama_base_url() == "http://localhost:11434"


def test_probe_never_raises_on_bad_input(monkeypatch):
    # _is_host_reachable itself, unmocked: a malformed URL must return
    # False, not propagate an exception up through the selector.
    assert O._is_host_reachable("not a url at all", timeout=0.01) is False


# ── factory wiring (adapters/llm_factory.get_provider) ──────────────────────

@pytest.fixture()
def db(tmp_path):
    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()
    yield dbmod
    dbmod.close_db()


def test_factory_uses_env_host_when_set(db, monkeypatch):
    from adapters.llm_factory import get_provider
    from adapters.config import save_config

    save_config({"llm_provider": "ollama", "ollama_url": "http://localhost:11434"})
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.113:11434")
    monkeypatch.setenv("OLLAMA_FALLBACK_URL", "http://localhost:11434")
    monkeypatch.setattr(O, "_is_host_reachable",
                        lambda url, timeout=1.5: url == "http://192.168.0.113:11434")

    provider = get_provider()
    assert provider._base == "http://192.168.0.113:11434"    # env wins over saved


def test_factory_falls_back_to_saved_setting_when_no_env(db, monkeypatch):
    from adapters.llm_factory import get_provider
    from adapters.config import save_config

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    save_config({"llm_provider": "ollama", "ollama_url": "http://saved-host:11434"})

    provider = get_provider()
    assert provider._base == "http://saved-host:11434"       # no env -> DB setting


def test_factory_env_model_overrides_both_tiers(db, monkeypatch):
    from adapters.llm_factory import get_provider
    from adapters.config import save_config

    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    save_config({"llm_provider": "ollama",
                "ollama_model_fast": "qwen2.5:3b-instruct",
                "ollama_model_smart": "llama3.1:70b"})

    provider = get_provider()
    assert provider._model_fast == "llama3.1:8b"
    assert provider._model_smart == "llama3.1:8b"


def test_factory_no_env_model_keeps_saved_per_tier_settings(db, monkeypatch):
    from adapters.llm_factory import get_provider
    from adapters.config import save_config

    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    save_config({"llm_provider": "ollama",
                "ollama_model_fast": "qwen2.5:3b-instruct",
                "ollama_model_smart": "llama3.1:70b"})

    provider = get_provider()
    assert provider._model_fast == "qwen2.5:3b-instruct"
    assert provider._model_smart == "llama3.1:70b"


def test_other_providers_unaffected_by_ollama_env_vars(db, monkeypatch):
    """The scoping guarantee: setting OLLAMA_* must not leak into any
    other provider's configuration."""
    from adapters.llm_factory import get_provider
    from adapters.config import save_config

    monkeypatch.setenv("OLLAMA_BASE_URL", "http://192.168.0.113:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    save_config({"llm_provider": "anthropic",
                "anthropic_api_key": "sk-ant-fake",
                "anthropic_model_smart": "claude-sonnet-4-6"})

    provider = get_provider()
    assert provider.__class__.__name__ == "AnthropicProvider"
    # No OLLAMA_* attribute leaked onto an unrelated provider instance.
    assert not hasattr(provider, "_base")
