"""
adapters/engine/tag_normalizer.py -- ISA tag quality checking, prefix
extraction, ISA-5.1 decoding, garbage-tag filtering, and instrument-type
normalization.

Extracted from adapters/engine.py (Phase 10), moved verbatim.
"""
from __future__ import annotations

import re

from .constants import (
    ANNOTATION_BLACKLIST, _RE_LINE_DESIG, _RE_DRAWING_NO, _GARBAGE_PFXS,
    _ISA_MEASURED_VAR, _ISA_FUNCTION_MAP, _SAFETY_VALVE_PREFIXES,
    _MECHANICAL_VALVE_PREFIXES, _DESCRIPTION_WORDS, _DESCRIPTION_PHRASES,
    _DCS_ABBREVIATIONS, _NON_PHYSICAL_STARTS, _NON_PHYSICAL_ALARM_SUFFIXES,
)


def _is_physical(prefix: str) -> bool:
    """Return False for tags that have no physical P&ID symbol (alarms, relays, operator outputs)."""
    p = prefix.upper()
    # Second letter Y → relay/compute block (FY, PY, TY, LY, AY)
    if len(p) >= 2 and p[1] == 'Y':
        return False
    # Compound alarm suffix: FAH, FAL, FAHH, FALL, PAH, PAHH, PALL, etc.
    for suf in _NON_PHYSICAL_ALARM_SUFFIXES:
        if len(p) > len(suf) and p.endswith(suf):
            return False
    # Standalone alarm / operator-output prefix
    for start in _NON_PHYSICAL_STARTS:
        if p == start or p.startswith(start):
            return False
    return True


def _check_tag_quality(tag: str) -> str:
    """
    Return quality flag: ok | placeholder | incomplete | description | annotation |
                         noise | line_number | label | abbreviation
    All non-ok qualities → physical=False, pid_layer=0 in classify_node.
    """
    if not tag:
        return 'incomplete'
    t = tag.strip().upper()

    # Pipe line designations contain "/" — check FIRST before any prefix matching
    # catches P-1101-1/2-T9L, P-3504-1/4-T3L, 4"-P-1001-1/2"-T9L, etc.
    if '/' in t:
        return 'line_number'

    # Exact description match (phrases with spaces or hyphens, single description words)
    if t in _DESCRIPTION_PHRASES or t in _DESCRIPTION_WORDS:
        return 'description'

    # Single-character OCR noise — stray letters (T, M, G, etc.)
    if len(t) == 1:
        return 'noise'

    # NC-HV-xxx = "normally closed hand valve" annotation, not a real tag
    if re.match(r'^NC-', t):
        return 'annotation'

    # Known DCS/motor abbreviations with no physical P&ID symbol
    if t in _DCS_ABBREVIATIONS:
        return 'abbreviation'

    # Extraction-tool annotation suffixes (HE-202A_tag, P-101_label)
    if re.search(r'[_](TAG|LABEL|NOTE)$', t):
        return 'annotation'

    # Placeholder tags (XXX, XXXX, etc.)
    if re.search(r'X{3,}', t):
        return 'placeholder'

    # Pure numbers — bare pipe/line numbers without letter prefix
    if re.match(r'^\d+$', t):
        return 'noise'

    # No digit AND no dash — short abbreviation / label, not an ISA instrument tag
    # (VFD, MSD, OA, HA, FC, TC, IN, ZK, WEO — already covered by _DCS_ABBREVIATIONS
    #  above for the known set, but catch any remaining unknowns here)
    if not re.search(r'\d', t) and '-' not in t:
        return 'label'

    return 'ok'


def _extract_prefix(tag: str) -> str:
    """Extract ISA prefix (letters before the first digit or hyphen+digit)."""
    t = tag.upper().strip()
    m = re.match(r'^([A-Z]{1,6})[-_]?\d', t)
    if m:
        return m.group(1)
    parts = re.split(r'[-_\d]', t)
    return parts[0][:6] if parts else t[:6]


def _isa_decode(prefix: str) -> dict | None:
    """
    Decode ISA prefix into classification fields.
    Returns partial dict or None if unrecognised.
    """
    p = prefix.upper()

    # Safety valves — highest priority (before general decode)
    if p in _SAFETY_VALVE_PREFIXES:
        return {'pid_layer': 4, 'category': 'relief_valve',
                'measured_variable': 'pressure', 'function': 'safety_valve',
                'valve_layer': 'relief_valves'}

    # Mechanical/isolation valves
    if p in _MECHANICAL_VALVE_PREFIXES:
        layer_map = {
            'HV': 'hand_valves', 'NV': 'hand_valves',
            'CK': 'check_valves', 'NRV': 'check_valves',
            'XV': 'isolation', 'SDV': 'isolation', 'BDV': 'isolation',
            'ESD': 'isolation', 'MOV': 'isolation', 'AOV': 'isolation',
            'SV': 'isolation', 'GV': 'hand_valves', 'BLV': 'hand_valves',
            'PBV': 'hand_valves',
        }
        cat_map = {
            'HV': 'hand_valve', 'NV': 'hand_valve',
            'CK': 'check_valve', 'NRV': 'check_valve',
        }
        vl = layer_map.get(p, 'isolation')
        cat = cat_map.get(p, 'isolation_valve')
        return {'pid_layer': 3, 'category': cat,
                'measured_variable': None, 'function': 'mechanical_valve',
                'valve_layer': vl}

    # Standard ISA decode: first letter = variable, remainder = function
    if len(p) < 2:
        return None

    # Special: HT = hot-side temperature indicator (compound prefix). The
    # single-letter 'H' decode would otherwise yield 'hand-transmitter',
    # which is wrong for AIRCO's HT-xxB convention on dual-service HXs.
    # Must come before the single-letter H + V check.
    if p == 'HT':
        return {'pid_layer': 2, 'category': 'indicator',
                'measured_variable': 'temperature',
                'function': 'hot_side_indicator',
                'valve_layer': None}

    first = p[0]
    suffix = p[1:]  # everything after first letter

    measured_var = _ISA_MEASURED_VAR.get(first)
    if not measured_var:
        return None

    # Special: H + V = hand valve (not control valve)
    if first == 'H' and 'V' in suffix:
        return {'pid_layer': 3, 'category': 'hand_valve',
                'measured_variable': 'hand', 'function': 'hand_valve',
                'valve_layer': 'hand_valves'}

    # Try longest matching suffix first
    for length in range(len(suffix), 0, -1):
        fsuffix = suffix[:length]
        if fsuffix in _ISA_FUNCTION_MAP:
            cat, layer = _ISA_FUNCTION_MAP[fsuffix]
            vl = None
            if layer == 1 and cat == 'control_valve':
                vl = 'ctrl_valves'
            return {'pid_layer': layer, 'category': cat,
                    'measured_variable': measured_var, 'function': fsuffix,
                    'valve_layer': vl}

    return None


def is_garbage_tag(tag: str, kind: str = '') -> bool:  # noqa: ARG001
    """
    Blacklist-based tag filter.  Returns True if the tag is obviously garbage
    (annotation text, drawing number, line designation, etc.) and should be
    discarded.  Returns False if the tag looks like a real equipment or
    instrument identifier — when in doubt it passes through.

    Claude already classified the tags during extraction, so this function only
    needs to catch the junk that leaked past the LLM, not enforce ISA naming.
    """
    if not tag:
        return True
    t = tag.strip()

    # Length bounds
    if len(t) < 2 or len(t) > 40:
        return True

    # Pure digits (page numbers, revision counters)
    if t.isdigit():
        return True

    # No alphanumeric characters at all
    if not re.search(r'[A-Za-z0-9]', t):
        return True

    # Known annotation words — full tag OR any space-separated token
    tu = t.upper()
    if tu in ANNOTATION_BLACKLIST:
        return True
    if any(w in ANNOTATION_BLACKLIST for w in tu.split()):
        return True

    # Ghost/annotation prefixes from extraction artefacts
    t_lo = t.lower()
    if any(t_lo.startswith(p) for p in _GARBAGE_PFXS):
        return True

    # Line designations: 2"-CS-150#, 4"-SS-300#, 6"-P-1001
    if _RE_LINE_DESIG.match(t):
        return True

    # Drawing numbers: 157-2-100, 965429-120-16
    if _RE_DRAWING_NO.match(t):
        return True

    # Multi-word ALL-CAPS annotation labels ("PROCESS FLOW", "COOLING WATER")
    # Single words (even all-caps) are fine — "REACTOR", "COLUMN" etc. pass
    words = t.split()
    if (len(words) >= 2
            and all(w.isalpha() for w in words)
            and t == t.upper()):
        return True

    # Everything else: let it through
    return False


def is_valid_isa_tag(tag: str, kind: str = '') -> bool:
    """Backward-compatible shim: returns True when the tag is NOT garbage."""
    return not is_garbage_tag(tag, kind)


def test_garbage_filter() -> None:
    """Smoke-test for is_garbage_tag().  Run: python -m adapters.engine"""
    should_pass = [
        ('FT-1001', ''),    ('TCV-201', 'valve'), ('2E0219', 'transmitter'),
        ('1065-V1', 'vessel'), ('2C0201A', 'compressor'), ('HE-202A', 'heat_exchanger'),
        ('TP-101', 'element'), ('PSV-1001', 'relief'), ('XV-100', 'valve'),
    ]
    should_fail = [
        ('NOTE', ''), ('REV', ''), ('157-2-100', ''), ('2"-CS-150#', ''),
        ('PROCESS FLOW', ''), ('3', ''), ('ghost_12', ''),
        ('SCALE 1:50', ''), ('A', ''),
    ]
    print('\n-- Tag Garbage Filter Test --')
    print('SHOULD PASS (not garbage):')
    ok = True
    for tag, kind in should_pass:
        garbage = is_garbage_tag(tag, kind)
        mark = 'OK' if not garbage else 'FAIL (wrongly rejected)'
        if garbage: ok = False
        print(f'  {mark}  {tag!r}')
    print('\nSHOULD FAIL (garbage):')
    for tag, kind in should_fail:
        garbage = is_garbage_tag(tag, kind)
        mark = 'OK' if garbage else 'FAIL (wrongly kept)'
        if not garbage: ok = False
        print(f'  {mark}  {tag!r}')
    print(f'\n{"All assertions passed" if ok else "FAILURES ABOVE"}\n')


def normalize_instrument_type(raw_type: str) -> str:
    """
    Map any Claude-returned type string to a valid YMPL instrument kind.
    Uses keyword pattern matching — handles the 90+ descriptive types
    Claude returns from real P&IDs.

    YMPL kinds: transmitter, controller, indicator, recorder,
                switch, analyzer, element
    """
    if not raw_type:
        return 'transmitter'

    t = raw_type.lower().strip()

    # Analyzer — check first (has 'analyzer' in name, not indicator/transmitter)
    if any(k in t for k in ('analyz', 'analyser', 'chromatograph', 'analyser')):
        if 'controller' in t:
            return 'controller'
        if 'transmitter' in t:
            return 'transmitter'
        return 'analyzer'

    # Recorder
    if 'recorder' in t or t in ('fr', 'pr', 'tr', 'lr', 'ar'):
        return 'recorder'

    # Controller — check before indicator (FIC = flow indicating CONTROLLER)
    if any(k in t for k in ('controller', 'controlling', 'loading_station',
                             'loading station', 'selector', 'totalizer',
                             'positioner', 'converter')):
        return 'controller'

    # Switch / alarm / relay / shutdown
    if any(k in t for k in ('switch', 'alarm', 'relay', 'solenoid',
                             'shutdown', 'trip', 'emergency', 'esd',
                             'heat_trac', 'heat trac', 'fuse',
                             'power alarm', 'high alarm', 'low alarm')):
        return 'switch'

    # Transmitter
    if any(k in t for k in ('transmitter', 'transducer')):
        return 'transmitter'

    # Indicator (after controller check to avoid false positives)
    if any(k in t for k in ('indicator', 'gauge', 'meter', 'light',
                             'lamp', 'annunciator', 'panel', 'status',
                             'monitor', 'display', 'sight', 'glass',
                             'speed_indicator', 'current_indicator',
                             'power transmitter', 'hand_pointer')):
        return 'indicator'

    # Element (sensing elements, wells, orifices)
    if any(k in t for k in ('element', 'well', 'orifice', 'pitot',
                             'sensor', 'probe', 'rtd', 'thermocouple',
                             'vibration', 'hand_tag', 'hand tag',
                             'computing', 'flow computing')):
        return 'element'

    # Variable frequency drive, power items → switch
    if any(k in t for k in ('drive', 'vfd', 'variable freq', 'power relay',
                             'pilot', 'instrument_air')):
        return 'switch'

    # Hand-operated items
    if 'hand' in t:
        if 'transmitter' in t:
            return 'transmitter'
        if 'switch' in t or 'valve' in t:
            return 'switch'
        return 'indicator'

    # Default: transmitter (safest — has range/units fields)
    return 'transmitter'
