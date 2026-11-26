"""Phase 1: LLM stage failure semantics.

The bug: `_call_llm_connections` caught every parse failure and returned
`{'edges': []}`. A truncated / fence-less / timed-out LLM-B reply therefore
persisted a drawing with all its symbols and none of its pipes, and the run
reported success. These tests pin the corrected contract.

Every LLM here is a fake callable. Nothing touches the network, a GPU, or a
model weight file.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

import extraction_cli.llm_verification as lv   # noqa: E402
from extraction_cli.llm_verification import (   # noqa: E402
    LlmStageError, _with_retries, _parse_llm_json, _call_llm_connections,
)


# -- a minimal stand-in for the `main` module the callers pass as `_s` --------

class _Resp:
    def __init__(self, text):
        self.text = text
        self.input_tokens = 10
        self.output_tokens = 20
        self.cost_usd = 0.001
        self.model = 'fake-model'
        self.provider = 'fake'


class _FakeLlm:
    """Replays a scripted list of replies; each entry is either a string
    (returned as the response text) or an Exception (raised)."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = 0

    def complete_streaming(self, *_a, **_k):
        self.calls += 1
        item = self.script.pop(0) if self.script else self.script_default()
        if isinstance(item, Exception):
            raise item
        return _Resp(item)

    def script_default(self):
        raise AssertionError('fake LLM called more times than scripted')


class _FakeStudio:
    """Stands in for `import main as _s`."""

    def __init__(self, script):
        self.llm = _FakeLlm(script)

    def load_skills(self, _kind):
        return 'system prompt'

    @staticmethod
    def extract_json(_raw):
        return None          # force the priority-3 path in _parse_llm_json


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Retry backoff must not make the suite slow."""
    import time
    monkeypatch.setattr(time, 'sleep', lambda *_a, **_k: None)


# -- _parse_llm_json ---------------------------------------------------------

def test_parses_a_json_fence():
    s = _FakeStudio([])
    out = _parse_llm_json(s, 'chatter\n```json\n{"edges": [1]}\n```\ntrailing', 'X')
    assert out == {'edges': [1]}


def test_parses_a_bare_object():
    s = _FakeStudio([])
    assert _parse_llm_json(s, '  {"edges": []}  ', 'X') == {'edges': []}


def test_strips_a_thinking_block():
    s = _FakeStudio([])
    raw = '<thinking>weighing it up</thinking>{"edges": [], "junctions": []}'
    assert _parse_llm_json(s, raw, 'X') == {'edges': [], 'junctions': []}


def test_raises_on_prose_with_no_json():
    s = _FakeStudio([])
    with pytest.raises(ValueError):
        _parse_llm_json(s, 'I could not read the drawing, sorry.', 'X')


def test_raises_on_truncated_json():
    s = _FakeStudio([])
    with pytest.raises(ValueError):
        _parse_llm_json(s, '{"edges": [{"from": "n1", "to"', 'X')


# -- bounded retries ---------------------------------------------------------

def test_retries_then_succeeds():
    attempts = {'n': 0}

    def flaky():
        attempts['n'] += 1
        if attempts['n'] < 3:
            raise TimeoutError('provider timeout')
        return 'ok'

    assert _with_retries('stage', flaky) == 'ok'
    assert attempts['n'] == 3


def test_retries_are_bounded_and_then_raise():
    attempts = {'n': 0}

    def always_fails():
        attempts['n'] += 1
        raise TimeoutError('provider timeout')

    with pytest.raises(LlmStageError):
        _with_retries('stage', always_fails)
    assert attempts['n'] == lv._LLM_MAX_ATTEMPTS, 'must not loop forever'


def test_llm_stage_error_names_the_stage():
    with pytest.raises(LlmStageError) as ei:
        _with_retries('llm_b_connections', lambda: (_ for _ in ()).throw(ValueError('x')))
    assert ei.value.stage == 'llm_b_connections'
    assert 'llm_b_connections' in str(ei.value)


# -- LLM B contract ----------------------------------------------------------

def _call_b(script):
    return _call_llm_connections(_FakeStudio(script), b'img', 'image/png',
                                 'summary', 'proposed')


def test_llm_b_valid_reply_passes_through():
    result, resp = _call_b(['{"edges": [{"from": "n1", "to": "n2", "kind": "process"}], "junctions": []}'])
    assert len(result['edges']) == 1
    assert resp.model == 'fake-model'


def test_llm_b_deliberate_empty_audit_is_honoured():
    """`"edges": []` from a model that DID answer is a real verdict and must
    not be confused with a failure."""
    result, _ = _call_b(['{"edges": [], "junctions": []}'])
    assert result['edges'] == []


def test_llm_b_missing_junctions_key_is_defaulted():
    result, _ = _call_b(['{"edges": []}'])
    assert result['junctions'] == []


def test_llm_b_invalid_json_raises_instead_of_returning_empty_edges():
    """The headline Phase 1 fix."""
    with pytest.raises(LlmStageError):
        _call_b(['not json at all'] * lv._LLM_MAX_ATTEMPTS)


def test_llm_b_missing_edges_key_is_a_schema_violation():
    with pytest.raises(LlmStageError):
        _call_b(['{"junctions": []}'] * lv._LLM_MAX_ATTEMPTS)


def test_llm_b_wrong_edges_type_is_a_schema_violation():
    with pytest.raises(LlmStageError):
        _call_b(['{"edges": "lots"}'] * lv._LLM_MAX_ATTEMPTS)


def test_llm_b_empty_response_raises():
    with pytest.raises(LlmStageError):
        _call_b([''] * lv._LLM_MAX_ATTEMPTS)


def test_llm_b_timeout_raises_after_bounded_retries():
    script = [TimeoutError('read timeout')] * lv._LLM_MAX_ATTEMPTS
    studio = _FakeStudio(script)
    with pytest.raises(LlmStageError):
        _call_llm_connections(studio, b'img', 'image/png', 'summary', 'proposed')
    assert studio.llm.calls == lv._LLM_MAX_ATTEMPTS


def test_llm_b_recovers_on_a_later_attempt():
    script = [TimeoutError('flaky'), '{"edges": [{"from":"a","to":"b","kind":"process"}]}']
    result, _ = _call_b(script)
    assert len(result['edges']) == 1
