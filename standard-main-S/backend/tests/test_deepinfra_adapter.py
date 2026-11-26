"""
tests/test_deepinfra_adapter.py — Comprehensive unit tests for DeepInfraProvider.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from openai import APIConnectionError, RateLimitError

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from adapters.llm_deepinfra import DeepInfraProvider, DEFAULT_BASE_URL, DEFAULT_MODEL
from adapters.llm_factory import get_provider
from adapters.vision_capability import supports_vision_for


def _make_fake_response(text: str = "OK", in_tok: int = 12, out_tok: int = 4):
    usage = SimpleNamespace(prompt_tokens=in_tok, completion_tokens=out_tok)
    message = SimpleNamespace(content=text)
    choice = SimpleNamespace(message=message)
    return SimpleNamespace(choices=[choice], usage=usage)


def test_deepinfra_env_fallback(monkeypatch):
    """Verify environment variables are used as fallbacks when config is unset."""
    monkeypatch.setenv("DEEPINFRA_API_KEY", "env-secret-key-123")
    monkeypatch.setenv("DEEPINFRA_BASE_URL", "https://custom.deepinfra.local/v1/openai")
    monkeypatch.setenv("DEEPINFRA_MODEL_SMART", "custom-gemma-smart")
    monkeypatch.setenv("DEEPINFRA_MODEL_FAST", "custom-gemma-fast")

    prov = DeepInfraProvider()
    assert prov._client.api_key == "env-secret-key-123"
    assert str(prov._client.base_url).rstrip("/") == "https://custom.deepinfra.local/v1/openai"
    assert prov._model_smart == "custom-gemma-smart"
    assert prov._model_fast == "custom-gemma-fast"
    assert prov._token_param == "max_tokens"


def test_deepinfra_explicit_args_override_env(monkeypatch):
    """Explicit parameters should override environment variables."""
    monkeypatch.setenv("DEEPINFRA_API_KEY", "env-key")
    monkeypatch.setenv("DEEPINFRA_MODEL_SMART", "env-model")

    prov = DeepInfraProvider(
        api_key="explicit-key",
        model="explicit-model",
        model_fast="explicit-fast",
        base_url="https://override.deepinfra.com/v1/openai",
    )
    assert prov._client.api_key == "explicit-key"
    assert prov._model_smart == "explicit-model"
    assert prov._model_fast == "explicit-fast"
    assert str(prov._client.base_url).rstrip("/") == "https://override.deepinfra.com/v1/openai"


def test_deepinfra_complete_and_trace_logging(capsys):
    """Verify text completion and structured trace telemetry."""
    prov = DeepInfraProvider(api_key="dummy-key", model="google/gemma-4-31B-it-turbo")
    fake_resp = _make_fake_response("Hello from DeepInfra", in_tok=25, out_tok=10)
    prov._client.chat.completions.create = MagicMock(return_value=fake_resp)

    resp = prov.complete("Generate summary", tier="fast")
    assert resp.text == "Hello from DeepInfra"
    assert resp.model == "google/gemma-4-31B-it-turbo"
    assert resp.provider == "deepinfra"
    assert resp.input_tokens == 25
    assert resp.output_tokens == 10
    assert resp.cost_usd > 0.0

    captured = capsys.readouterr().out
    assert "[DeepInfra] 🚀 START | Model: google/gemma-4-31B-it-turbo | Tier: fast" in captured
    assert "[DeepInfra] ✅ DONE  | Duration:" in captured
    assert "Tokens: 25/10" in captured


def test_deepinfra_complete_streaming_with_image(capsys):
    """Verify vision streaming call formats image_url and logs traces."""
    prov = DeepInfraProvider(api_key="dummy-key", model="google/gemma-4-31B-it-turbo")
    fake_resp = _make_fake_response("Bounding boxes detected", in_tok=500, out_tok=80)
    prov._client.chat.completions.create = MagicMock(return_value=fake_resp)

    resp = prov.complete_streaming(
        "Detect equipment",
        image_b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
        media_type="image/png",
        tier="smart",
    )
    assert resp.text == "Bounding boxes detected"
    call_args = prov._client.chat.completions.create.call_args[1]
    assert call_args["model"] == "google/gemma-4-31B-it-turbo"
    assert "max_tokens" in call_args
    # Check image_url was added
    user_msg = call_args["messages"][0]["content"]
    assert any(item.get("type") == "image_url" for item in user_msg)

    captured = capsys.readouterr().out
    assert "[DeepInfra] 🚀 START | Model: google/gemma-4-31B-it-turbo | Tier: smart" in captured
    assert "[DeepInfra] ✅ DONE" in captured


def test_deepinfra_rate_limit_retry(monkeypatch, capsys):
    """Verify EnGenie two-tier retry: 429 RateLimitError triggers 20s backoff and succeeds on retry."""
    prov = DeepInfraProvider(api_key="dummy-key")

    # Mock time.sleep to avoid waiting real 20 seconds during test
    slept_durations = []
    monkeypatch.setattr("time.sleep", lambda secs: slept_durations.append(secs))

    fake_resp = _make_fake_response("Success after rate limit")
    mock_request = MagicMock()
    rate_limit_err = RateLimitError("Rate limit reached", response=MagicMock(status_code=429), body=None)

    # First call fails with 429, second call succeeds
    prov._client.chat.completions.create = MagicMock(side_effect=[rate_limit_err, fake_resp])

    resp = prov.complete("Test prompt")
    assert resp.text == "Success after rate limit"
    assert len(slept_durations) == 1
    # Check that backoff was >= 20 seconds
    assert slept_durations[0] >= 20.0

    captured = capsys.readouterr().out
    assert "[DeepInfra] ⚠️ Rate limit encountered (429). Backing off for" in captured
    assert "(attempt 1/3)" in captured
    assert "[DeepInfra] ✅ DONE" in captured


def test_deepinfra_rate_limit_exhausted(monkeypatch, capsys):
    """Verify RateLimitError raises after 3 retries."""
    prov = DeepInfraProvider(api_key="dummy-key")
    monkeypatch.setattr("time.sleep", lambda secs: None)

    rate_limit_err = RateLimitError("Rate limit reached", response=MagicMock(status_code=429), body=None)
    prov._client.chat.completions.create = MagicMock(side_effect=rate_limit_err)

    with pytest.raises(RateLimitError):
        prov.complete("Test prompt")

    captured = capsys.readouterr().out
    assert "[DeepInfra] ❌ Rate limit (429) retry attempts exhausted" in captured
    assert "[DeepInfra] ❌ FAILED" in captured


def test_deepinfra_transient_connection_retry(monkeypatch, capsys):
    """Verify transient connection errors retry with jitter and succeed."""
    prov = DeepInfraProvider(api_key="dummy-key")
    monkeypatch.setattr("time.sleep", lambda secs: None)

    fake_resp = _make_fake_response("Success after network blip")
    conn_err = APIConnectionError(request=MagicMock())

    prov._client.chat.completions.create = MagicMock(side_effect=[conn_err, fake_resp])

    resp = prov.complete("Test prompt")
    assert resp.text == "Success after network blip"

    captured = capsys.readouterr().out
    assert "[DeepInfra] ⚠️ Transient network error:" in captured
    assert "(attempt 1/3)" in captured
    assert "[DeepInfra] ✅ DONE" in captured


def test_deepinfra_factory_resolution(monkeypatch):
    """Verify get_provider('deepinfra') and get_provider('custom:deepinfra')."""
    monkeypatch.setenv("DEEPINFRA_API_KEY", "env-test-key")

    prov1 = get_provider("deepinfra")
    assert isinstance(prov1, DeepInfraProvider)
    assert prov1.provider_name == "deepinfra"

    prov2 = get_provider("custom:deepinfra")
    assert isinstance(prov2, DeepInfraProvider)
    assert prov2.provider_name == "deepinfra"


def test_deepinfra_vision_capability():
    """Verify vision capability classification for DeepInfra models."""
    # Multimodal / Vision models on DeepInfra
    assert supports_vision_for("deepinfra", "meta-llama/Llama-3.2-11B-Vision-Instruct") is True
    assert supports_vision_for("deepinfra", "Qwen/Qwen2-VL-72B-Instruct") is True
    assert supports_vision_for("deepinfra", "google/gemma-4-31B-it-turbo") is True
    assert supports_vision_for("custom:deepinfra", "google/gemma-4-31B-it-turbo") is True

    # Known text-only open models on DeepInfra
    assert supports_vision_for("deepinfra", "google/gemma-2-27b-it") is False
    assert supports_vision_for("deepinfra", "google/gemma-1.1-7b-it") is False
    assert supports_vision_for("deepinfra", "meta-llama/Llama-3.1-8B-Instruct") is False
    assert supports_vision_for("deepinfra", "meta-llama/Llama-3.3-70B-Instruct") is False
    assert supports_vision_for("deepinfra", "deepseek-ai/DeepSeek-V3") is False


def test_deepinfra_settings_test_connection(monkeypatch):
    """Verify settings controller test_llm_connection for deepinfra."""
    from controllers import settings_controller
    from flask_compat import request

    fake_resp = _make_fake_response("OK")
    monkeypatch.setattr(
        DeepInfraProvider,
        "_create",
        lambda self, **kwargs: fake_resp,
    )

    class FakeRequest:
        def get_json(self, *args, **kwargs):
            return {
                "llm_provider": "deepinfra",
                "deepinfra_api_key": "test-key",
            }

    monkeypatch.setattr(settings_controller, "request", FakeRequest())
    res = settings_controller.test_llm_connection()
    # Starlette JSONResponse
    import json
    body = json.loads(res.body.decode("utf-8"))
    assert res.status_code == 200
    assert body["ok"] is True
    assert body["reply"] == "OK"
