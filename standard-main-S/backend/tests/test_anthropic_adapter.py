"""adapters/llm_anthropic.py request shape, checked offline with a fake client.

Pins three fixes:
  * JSON mode used assistant prefill on every model. Opus 4.6+/Sonnet 4.6+
    reject prefill with HTTP 400, and the default smart tier is
    claude-sonnet-4-6, so LLM A verification failed on the default config.
  * The system prompt is sent as a cacheable block, and cache reads/writes are
    recorded and priced.
  * The cost table priced Haiku 4.5 at $0.25/$1.25 instead of $1/$5.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

STUDIO = Path(__file__).resolve().parent.parent
if str(STUDIO) not in sys.path:
    sys.path.insert(0, str(STUDIO))

from adapters import llm_anthropic as A  # noqa: E402


class _FakeStream:
    def __init__(self, recorder, text, usage):
        self.recorder, self.text, self.usage = recorder, text, usage

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return SimpleNamespace(usage=self.usage)

    def get_final_text(self):
        return self.text


def _provider(model_fast, model_smart, text='"ok": true}', **usage):
    calls = []
    provider = A.AnthropicProvider.__new__(A.AnthropicProvider)
    provider._model_fast, provider._model_smart, provider._temperature = model_fast, model_smart, 0.0
    usage_ns = SimpleNamespace(input_tokens=usage.get("input", 100), output_tokens=usage.get("output", 20),
                               cache_creation_input_tokens=usage.get("write", 0),
                               cache_read_input_tokens=usage.get("read", 0))
    provider._client = SimpleNamespace(messages=SimpleNamespace(
        stream=lambda **kw: (calls.append(kw), _FakeStream(calls, text, usage_ns))[1]))
    return provider, calls


@pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-8", "claude-opus-5",
                                   "claude-sonnet-5", "claude-fable-5-1", "some-future-model"])
def test_json_mode_never_prefills_models_that_reject_it(model):
    provider, calls = _provider("claude-haiku-4-5-20251001", model, text='{"ok": true}')
    resp = provider.complete_streaming("Extract.", force_json=True, tier="smart")
    messages = calls[0]["messages"]
    assert [m["role"] for m in messages] == ["user"], "no assistant prefill turn"
    assert "Respond with only the JSON object" in messages[0]["content"]
    assert resp.text == '{"ok": true}', "no stray '{' prepended"


def test_json_mode_still_prefills_haiku_4_5():
    provider, calls = _provider("claude-haiku-4-5-20251001", "claude-sonnet-4-6")
    resp = provider.complete_streaming("Extract.", force_json=True, tier="fast")
    assert calls[0]["messages"][-1] == {"role": "assistant", "content": "{"}
    assert resp.text == '{"ok": true}'


def test_system_prompt_is_a_cacheable_block_before_the_image():
    provider, calls = _provider("claude-haiku-4-5-20251001", "claude-sonnet-4-6")
    provider.complete_streaming("Tile.", system="STATIC INSTRUCTIONS", image_b64="aGk=",
                                media_type="image/png", tier="smart")
    kw = calls[0]
    assert kw["system"] == [{"type": "text", "text": "STATIC INSTRUCTIONS",
                             "cache_control": {"type": "ephemeral"}}]
    content = kw["messages"][0]["content"]
    assert content[0]["type"] == "image" and content[-1] == {"type": "text", "text": "Tile."}


def test_no_system_means_no_system_field():
    provider, calls = _provider("claude-haiku-4-5-20251001", "claude-sonnet-4-6")
    provider.complete_streaming("Hi.", tier="smart")
    assert "system" not in calls[0]


def test_cache_usage_is_recorded_and_priced():
    provider, _ = _provider("claude-haiku-4-5-20251001", "claude-sonnet-4-6",
                            input=1_000_000, output=0, write=1_000_000, read=1_000_000)
    resp = provider.complete_streaming("x", system="s", tier="smart")
    assert resp.cache_creation_input_tokens == 1_000_000
    assert resp.cache_read_input_tokens == 1_000_000
    # Sonnet 4.6 at $3/M input: 1M uncached + 1M written at 1.25x + 1M read at 0.1x
    assert resp.cost_usd == pytest.approx(3.00 + 3.75 + 0.30)


@pytest.mark.parametrize("model, rates", [
    ("claude-haiku-4-5-20251001", (1.00, 5.00)),
    ("claude-sonnet-4-6", (3.00, 15.00)),
    ("claude-opus-4-7", (5.00, 25.00)),
    ("claude-opus-5", (5.00, 25.00)),
    ("claude-fable-5-1", (10.00, 50.00)),
])
def test_cost_table_uses_current_prices(model, rates):
    assert A._rates(model) == rates


def test_prefill_support_table():
    assert A._supports_prefill("claude-haiku-4-5-20251001")
    assert A._supports_prefill("claude-sonnet-4-5")
    assert not A._supports_prefill("claude-sonnet-4-6")
    assert not A._supports_prefill("claude-opus-4-6")
    assert not A._supports_prefill("")
