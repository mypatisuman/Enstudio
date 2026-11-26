"""Tests for test_ollama.py — the standalone Ollama connectivity/testing
CLI. No real network access: urlopen is mocked. Verifies the tool's own
logic (parsing, --save scoping, error handling), not a live Ollama server.
"""
import io
import json
import sys
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

STUDIO_DIR = Path(__file__).parent.parent
if str(STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(STUDIO_DIR))

import test_ollama as T  # noqa: E402


def _fake_response(payload: dict):
    body = json.dumps(payload).encode()
    cm = MagicMock()
    cm.__enter__.return_value = io.BytesIO(body)
    cm.__exit__.return_value = False
    return cm


def test_format_models_extracts_names():
    tags = {"models": [{"name": "llama3.1:70b"}, {"name": "qwen2.5:3b-instruct"}]}
    assert T.format_models(tags) == ["llama3.1:70b", "qwen2.5:3b-instruct"]


def test_format_models_empty():
    assert T.format_models({"models": []}) == []
    assert T.format_models({}) == []


def test_probe_tags_strips_trailing_v1(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        return _fake_response({"models": []})

    monkeypatch.setattr(T.urllib.request, "urlopen", fake_urlopen)
    T.probe_tags("http://host:11434/v1")
    assert captured["url"] == "http://host:11434/api/tags"


def test_probe_tags_unreachable_raises(monkeypatch):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(T.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(urllib.error.URLError):
        T.probe_tags("http://unreachable-host:11434")


def test_run_completion_uses_ollama_provider(monkeypatch):
    from adapters.llm_provider import LLMResponse

    calls = {}

    class FakeProvider:
        def __init__(self, base_url, model_fast, model_smart):
            calls["init"] = (base_url, model_fast, model_smart)

        def complete(self, prompt, *, max_tokens, tier):
            calls["complete"] = (prompt, max_tokens, tier)
            return LLMResponse(text="yes", model=model_smart_stub, provider="ollama")

    model_smart_stub = "qwen2.5:3b-instruct"
    monkeypatch.setattr("adapters.llm_ollama.OllamaProvider", FakeProvider)

    text, elapsed = T.run_completion("http://host:11434", "qwen2.5:3b-instruct",
                                     "hello", max_tokens=50)
    assert text == "yes"
    assert elapsed >= 0
    assert calls["init"] == ("http://host:11434", "qwen2.5:3b-instruct",
                             "qwen2.5:3b-instruct")
    assert calls["complete"] == ("hello", 50, "fast")


# ── end-to-end main() with mocked network ────────────────────────────────────

def test_main_unreachable_returns_1(monkeypatch, capsys):
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError("refused")
    monkeypatch.setattr(T.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(sys, "argv", ["test_ollama.py", "--url",
                                      "http://unreachable:11434"])
    assert T.main() == 1
    assert "UNREACHABLE" in capsys.readouterr().out


def test_main_reachable_no_models_no_arg_returns_1(monkeypatch, capsys):
    monkeypatch.setattr(T.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response({"models": []}))
    monkeypatch.setattr(sys, "argv", ["test_ollama.py", "--url",
                                      "http://host:11434"])
    assert T.main() == 1
    assert "No --model given and no models pulled" in capsys.readouterr().out


def test_main_full_success_does_not_touch_settings(monkeypatch, capsys):
    """Without --save, settings must never be imported/written — proves
    the tool cannot silently change the app's active provider."""
    monkeypatch.setattr(T.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"models": [{"name": "llama3.1:70b"}]}))

    from adapters.llm_provider import LLMResponse

    class FakeProvider:
        def __init__(self, base_url, model_fast, model_smart):
            pass

        def complete(self, prompt, *, max_tokens, tier):
            return LLMResponse(text="yes", model="llama3.1:70b", provider="ollama")

    monkeypatch.setattr("adapters.llm_ollama.OllamaProvider", FakeProvider)

    save_config_called = MagicMock()
    monkeypatch.setattr("adapters.config.save_config", save_config_called)

    monkeypatch.setattr(sys, "argv", ["test_ollama.py", "--url",
                                      "http://192.168.1.50:11434"])
    assert T.main() == 0
    out = capsys.readouterr().out
    assert "OK — server responding" in out
    assert "Response: 'yes'" in out
    save_config_called.assert_not_called()


def test_main_save_requires_hub(monkeypatch, capsys):
    monkeypatch.setattr(T.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"models": [{"name": "llama3.1:70b"}]}))
    monkeypatch.setattr(sys, "argv", ["test_ollama.py", "--url",
                                      "http://192.168.1.50:11434", "--save"])
    assert T.main() == 1
    assert "--save requires --hub" in capsys.readouterr().out


def test_main_save_persists_without_changing_provider(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(T.urllib.request, "urlopen",
                        lambda req, timeout=None: _fake_response(
                            {"models": [{"name": "llama3.1:70b"}]}))

    from adapters.llm_provider import LLMResponse

    class FakeProvider:
        def __init__(self, base_url, model_fast, model_smart):
            pass

        def complete(self, prompt, *, max_tokens, tier):
            return LLMResponse(text="yes", model="llama3.1:70b", provider="ollama")

    monkeypatch.setattr("adapters.llm_ollama.OllamaProvider", FakeProvider)

    from adapters import db as dbmod
    dbmod.reset_for_path(tmp_path / "studio.db")
    dbmod.init_db()

    monkeypatch.setattr(sys, "argv", [
        "test_ollama.py", "--url", "http://192.168.1.50:11434",
        "--model", "llama3.1:70b", "--save", "--hub", str(tmp_path)])
    assert T.main() == 0

    from adapters.config import load_config
    cfg = load_config()
    assert cfg["ollama_url"] == "http://192.168.1.50:11434"
    # F1.7 fix: both tiers get saved, not just fast — Ollama models are
    # one size class, unlike the hosted APIs' distinct fast/smart pair.
    assert cfg["ollama_model_fast"] == "llama3.1:70b"
    assert cfg["ollama_model_smart"] == "llama3.1:70b"
    # The whole point: llm_provider is untouched, still the default.
    assert cfg["llm_provider"] == "anthropic"
    dbmod.close_db()
