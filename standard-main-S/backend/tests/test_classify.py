"""classify_node tests — company-specific instrument prefix handling.

Covers:
  * HT- compound prefix → indicator (ISA decode special case)
  * JE- / JT- (J = power) — variable + no controller expected (conventions)
  * RT- (R = ratio) — picked up via Section 10 default-assumptions bullet
  * Standard FT- still classifies as transmitter
  * Unknown prefix falls through to ISA / kind defaults
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_STUDIO_DIR = Path(__file__).resolve().parents[1]
if str(_STUDIO_DIR) not in sys.path:
    sys.path.insert(0, str(_STUDIO_DIR))

from adapters.engine import classify_node                # noqa: E402
from adapters.company import CompanyConventions          # noqa: E402


# The merged loader pulls the registry baseline (always shipped) AND any
# HUB project-local override (may or may not exist). The HUB override path
# is deliberately pointed at a non-existent dir so tests are hermetic.
_FAKE_HUB = _STUDIO_DIR / 'tests' / '_no_hub'


@pytest.fixture(scope='module')
def airco_conventions() -> CompanyConventions:
    return CompanyConventions._load_merged('AIRCO', _FAKE_HUB)


# ── Company-specific prefixes ────────────────────────────────────────────────

def test_HT_classifies_as_indicator_no_controller(airco_conventions):
    r = classify_node('HT-2001B', 'transmitter', conventions=airco_conventions)
    assert r['category']           == 'indicator'
    assert r['expects_controller'] is False
    assert r['measured_variable']  == 'temperature'


def test_JE_classifies_as_element_power(airco_conventions):
    r = classify_node('JE-2002', 'element', conventions=airco_conventions)
    assert r['category']           == 'element'
    assert r['measured_variable']  == 'power'
    assert r['expects_controller'] is False


def test_JT_classifies_as_transmitter_power(airco_conventions):
    r = classify_node('JT-9001', 'transmitter', conventions=airco_conventions)
    assert r['category']           == 'transmitter'
    assert r['measured_variable']  == 'power'
    assert r['expects_controller'] is False


def test_RT_classifies_as_transmitter_ratio(airco_conventions):
    """RT- isn't in Section 3 — it must be picked up via the Section 10
    default-assumptions bullet."""
    r = classify_node('RT-1102', 'transmitter', conventions=airco_conventions)
    assert r['category']           == 'transmitter'
    assert r['measured_variable']  == 'ratio'
    assert r['expects_controller'] is False


# ── Standard prefixes / fallthrough ──────────────────────────────────────────

def test_FT_unchanged_still_transmitter(airco_conventions):
    """A standard ISA prefix that has no company-specific override must
    classify exactly as before — ISA decode wins."""
    r = classify_node('FT-1052', 'transmitter', conventions=airco_conventions)
    assert r['category']          == 'transmitter'
    assert r['measured_variable'] == 'flow'
    # No expects_controller override — conventions returned None
    assert 'expects_controller' not in r or r['expects_controller'] is True


def test_unknown_prefix_falls_through_to_isa(airco_conventions):
    """A prefix that's neither in conventions nor a recognised ISA letter
    falls through to the kind-field branch and yields the default fields."""
    r = classify_node('ZQR-9999', 'transmitter', conventions=airco_conventions)
    # No conventions hit, ISA decode returns None (Z is in _ISA_MEASURED_VAR
    # but ZQR has no matching function suffix), so result comes from the
    # kind argument.
    assert r['category'] in ('transmitter', 'equipment')
    # Crucially: no spurious expects_controller field from conventions
    assert 'expects_controller' not in r
