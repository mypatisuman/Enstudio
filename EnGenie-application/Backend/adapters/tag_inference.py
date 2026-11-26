"""
tag_inference.py — Pass 3 tag normalisation + inference

Runs after Pass 2.5 (pipe runs) and before nodes are written to espx.
Repairs OCR-corrupted tags, snaps near-misses to known tags, and proposes
tags for nodes the extractor never named.

Public API:
    normalize_tag(raw_tag, area, kind, known_tags) -> dict | None
    infer_tag(node, all_nodes, edges, known_tags)  -> dict | None
    run_tag_inference(nodes, edges)                -> list[dict]

Each non-None result is a "proposal" dict with the keys
    proposed       — the corrected/inferred tag string
    confidence     — 0.0–1.0
    method         — substitution | structural | fuzzy | inferred
    review_state   — auto (≥0.9) | uncertain | inferred

run_tag_inference returns proposals keyed by node_id; the caller decides
how to apply them (auto → write tag, otherwise store under _tag_proposal).
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Dict, Iterable, List, Optional, Tuple

from adapters.engine import is_garbage_tag, is_valid_isa_tag, PROCESS_KINDS, INSTRUMENT_KINDS


# ── OCR character substitutions (common scanner / extractor confusions) ───────
# These are applied to the NUMERIC portion of a tag — letters that the OCR
# engine confused with the visually-similar digit.
_OCR_DIGIT_FOR_LETTER = {
    'O': '0', 'o': '0',
    'I': '1', 'l': '1',
    'S': '5',
    'B': '8',
    'Z': '2',
    'G': '6',
}


# ── Confidence thresholds ─────────────────────────────────────────────────────

_AUTO_THRESHOLD = 0.9
_INFERRED_CAP   = 0.75   # spec: inferred tags must always have confidence ≤ this


# ── Function-letter table (ISA-5.1 mapping for non-instrument equipment) ──────

_KIND_PREFIX = {
    'vessel':         'V',
    'separator':      'V',
    'pump':           'P',
    'heat_exchanger': 'E',
    'compressor':     'C',
    'filter':         'F',
    'reactor':        'R',
    'column':         'C',
    'absorber':       'C',
    'meter':          'FE',
}

# Measured variable → ISA first-letter
_VAR_TO_LETTER = {
    'flow':        'F',
    'temperature': 'T',
    'temp':        'T',
    'pressure':    'P',
    'press':       'P',
    'level':       'L',
    'composition': 'A',
    'analyzer':    'A',
}


# ── Levenshtein distance (small, no deps) ─────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(cur[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[-1]


# ── Tag-shape helpers ─────────────────────────────────────────────────────────

_RX_VALID_SHAPE   = re.compile(r'^[A-Z]{1,5}-\d+[A-Za-z]?$')
_RX_LETTERS_ONLY  = re.compile(r'^[A-Za-z]+$')
_RX_DIGITS_ONLY   = re.compile(r'^\d+$')
_RX_SPLIT_LETTERS = re.compile(r'^([A-Za-z]+)[-_ ]?(.*)$')


def _is_clean_tag(tag: str, kind: str) -> bool:
    """Stricter than engine.is_valid_isa_tag: also requires the canonical
    shape `LETTERS-DIGITS[A|B]`. The engine validator only checks for any
    '-digit' substring, which lets 'FT-1O52' pass — that's exactly the case
    Pass 3 needs to repair."""
    if is_garbage_tag(tag, kind):
        return False
    if kind in PROCESS_KINDS:
        # Equipment tags can be looser (engine policy); accept anything the
        # base validator accepts.
        return True
    return bool(_RX_VALID_SHAPE.match(tag))


def _split_prefix_number(tag: str) -> Optional[Tuple[str, str, str]]:
    """Best-effort split of 'FT-1052' / 'FT1052' / 'F-T1052' / 'FT-I052' into
    (letters, digits_after_ocr_fix, ab_suffix).

    Strategy: strip separators, peel an optional single A/B side-suffix off
    the tail, then walk the tail backwards consuming digits + OCR-letters
    (O,I,l,S,B,Z,G) until a "real" letter blocks the walk. Letters before
    that blocker are the prefix; the consumed tail is the (OCR-fixed)
    number portion. Returns None if either side is empty or the prefix
    isn't all letters.
    """
    if not tag:
        return None
    stripped = tag.replace('-', '').replace('_', '').replace(' ', '')
    if not stripped:
        return None

    # Optional trailing side-suffix (A/B) — only one letter, and only if the
    # char immediately before it is a real digit. We deliberately do NOT treat
    # an OCR-letter (B/Z/G/…) as the "anchor" digit, because that would let a
    # genuine side suffix like 'B' get consumed as OCR noise (see
    # 'HV-4004Bb' → 'HV-40048B' regression).
    side = ''
    if (len(stripped) >= 2 and stripped[-1].isalpha() and
            stripped[-1] not in _OCR_DIGIT_FOR_LETTER):
        prev = stripped[-2]
        if prev.isdigit():
            side = stripped[-1].upper()
            stripped = stripped[:-1]

    # Walk the tail backwards consuming digits + OCR-letters.
    # Guard: B/Z/G appearing AFTER the last digit (i.e. before any digit has
    # been seen on the walk) are side suffixes (A/B/C…), not OCR noise — so
    # we stop the walk instead of substituting them. O/I/l/S remain
    # substitutable everywhere because they are vanishingly rare side suffixes.
    _SIDE_SAFE = set('BZGbzg')
    i = len(stripped)
    seen_digit = False
    while i > 0:
        c = stripped[i - 1]
        if c.isdigit():
            seen_digit = True
            i -= 1
            continue
        if c in _OCR_DIGIT_FOR_LETTER:
            if c in _SIDE_SAFE and not seen_digit:
                break
            i -= 1
            continue
        break
    prefix     = stripped[:i]
    number_raw = stripped[i:]

    if not prefix or not number_raw:
        return None
    if not _RX_LETTERS_ONLY.match(prefix):
        return None
    digits_fixed = ''.join(_OCR_DIGIT_FOR_LETTER.get(c, c) for c in number_raw)
    if not _RX_DIGITS_ONLY.match(digits_fixed):
        return None
    return prefix.upper(), digits_fixed, side


def _format_canonical(letters: str, digits: str, suffix: str = '') -> str:
    return f'{letters}-{digits}{suffix}'


def _digits_of(tag: str) -> Optional[int]:
    m = re.search(r'(\d+)', tag or '')
    return int(m.group(1)) if m else None


def _prefix_of(tag: str) -> str:
    m = re.match(r'^([A-Za-z]+)', tag or '')
    return m.group(1).upper() if m else ''


# ── normalize_tag ─────────────────────────────────────────────────────────────

def normalize_tag(raw_tag: str,
                  area: str,
                  kind: str,
                  known_tags: Iterable[str]) -> Optional[dict]:
    """Repair OCR / structural mistakes in `raw_tag`.

    Tries, in order:
      1. character substitution for OCR confusions
      2. structural repair (insert missing hyphen, drop stray internal hyphens)
      3. fuzzy match against `known_tags` (Levenshtein ≤ 2; same-area preferred)

    Returns the first proposal whose tag passes is_valid_isa_tag, or None.
    """
    if raw_tag is None:
        return None
    raw = raw_tag.strip()
    if not raw:
        return None
    if _is_clean_tag(raw, kind):
        return None  # already good — nothing to do

    known_list = [t for t in known_tags if t]
    same_area_tags = set()  # filled below if caller supplies area-aware list
    # Caller is free to pass a flat list; we'll use area information only if a
    # known tag's prefix matches the area's typical prefix.

    # --- 1+2. Substitution + structural repair --------------------------------
    # Skip multi-segment strings (e.g. line tags 'RV-4502-1' or pipe specs
    # 'H-0501-1/2-TNL'): they are not single-tag mistakes and rejoining their
    # segments would silently corrupt them.
    if raw.count('-') > 1 or '/' in raw or '.' in raw:
        return _fuzzy_only(raw, kind, known_list)

    # _split_prefix_number applies OCR digit-for-letter on the number portion.
    # If any character in that portion needed substitution, classify as
    # 'substitution'; otherwise the only change was a hyphen insert/move →
    # classify as 'structural'.
    parts = _split_prefix_number(raw)
    if parts:
        letters, digits, suffix = parts
        # Recover the raw (un-substituted) number portion to detect whether
        # OCR substitution actually fired.
        stripped = raw.replace('-', '').replace('_', '').replace(' ', '')
        if suffix and stripped.endswith(suffix):
            stripped_no_side = stripped[:-len(suffix)]
        else:
            stripped_no_side = stripped
        raw_number = stripped_no_side[len(letters):]
        used_substitution = any(c in _OCR_DIGIT_FOR_LETTER for c in raw_number)

        repaired = _format_canonical(letters, digits, suffix)
        if repaired != raw and _is_clean_tag(repaired, kind):
            return {
                'proposed':     repaired,
                'confidence':   0.9 if used_substitution else 0.95,
                'method':       'substitution' if used_substitution else 'structural',
                'review_state': 'auto',
            }

    # --- 3. Fuzzy match against known tags -----------------------------------
    target = (parts and _format_canonical(*parts)) or raw.upper()
    best: Optional[Tuple[int, str]] = None
    for kt in known_list:
        if kt.upper() == target:
            continue  # distance 0 → "match" is the input itself; skip
        d = _levenshtein(target, kt.upper())
        if d <= 2 and (best is None or d < best[0]):
            best = (d, kt)
    if best:
        d, kt = best
        confidence = 0.85 if d == 1 else 0.7
        return {
            'proposed':     kt,
            'confidence':   confidence,
            'method':       'fuzzy',
            'review_state': 'auto' if confidence >= _AUTO_THRESHOLD else 'uncertain',
        }

    return None


def _fuzzy_only(raw: str, kind: str, known_list: List[str]) -> Optional[dict]:
    """Fallback path: only fuzzy-match against known tags."""
    target = raw.upper()
    best: Optional[Tuple[int, str]] = None
    for kt in known_list:
        if kt.upper() == target:
            continue
        d = _levenshtein(target, kt.upper())
        if d <= 2 and (best is None or d < best[0]):
            best = (d, kt)
    if not best:
        return None
    d, kt = best
    confidence = 0.85 if d == 1 else 0.7
    return {
        'proposed':     kt,
        'confidence':   confidence,
        'method':       'fuzzy',
        'review_state': 'auto' if confidence >= _AUTO_THRESHOLD else 'uncertain',
    }


# ── infer_tag ─────────────────────────────────────────────────────────────────

def infer_tag(node: dict,
              all_nodes: List[dict],
              edges: List[dict],
              known_tags: Iterable[str]) -> Optional[dict]:
    """Propose a tag for a node that has no tag at all.

    Resolves the function-letter prefix from kind / measured variable / signal
    context, then picks a loop number by filling a gap in the existing
    same-area sequence (or area-prefix + next-free if no sequence exists).
    """
    kind = (node.get('kind') or '').lower()
    area = node.get('area') or ''

    prefix = _prefix_for_node(node, all_nodes, edges)
    if not prefix:
        return None

    same_area_tags = _tags_in_area(all_nodes, area, prefix, known_tags)
    next_num = _next_loop_number(same_area_tags, area, all_nodes, prefix, known_tags)
    if next_num is None:
        return None

    proposed = _format_canonical(prefix, str(next_num))
    # Confidence is capped — inferred tags require human review.
    if same_area_tags:
        confidence = 0.75
    else:
        confidence = 0.5
    return {
        'proposed':     proposed,
        'confidence':   min(confidence, _INFERRED_CAP),
        'method':       'inferred',
        'review_state': 'inferred',
    }


def _prefix_for_node(node: dict, all_nodes: List[dict], edges: List[dict]) -> str:
    """Best-effort ISA prefix for a node based on kind, measured variable, and
    signal connections."""
    kind = (node.get('kind') or '').lower()

    # Direct equipment kinds
    if kind in _KIND_PREFIX and kind not in INSTRUMENT_KINDS and kind != 'valve':
        return _KIND_PREFIX[kind]

    # Instruments: derive variable letter + function letter
    if kind in INSTRUMENT_KINDS:
        var = (node.get('measured_variable') or
               node.get('variable') or '').lower()
        var_letter = _VAR_TO_LETTER.get(var, '')
        if not var_letter:
            # Try to pull from a connected controller / transmitter tag
            nbr_tag = _first_neighbour_tag(node, all_nodes, edges, signal_only=True)
            if nbr_tag:
                var_letter = _prefix_of(nbr_tag)[:1]
        if not var_letter:
            return ''
        if kind == 'transmitter':
            return f'{var_letter}T'
        if kind == 'controller':
            return f'{var_letter}IC'
        if kind == 'indicator':
            return f'{var_letter}I'
        if kind == 'recorder':
            return f'{var_letter}R'
        if kind == 'switch':
            return f'{var_letter}S'
        if kind == 'analyzer':
            return f'{var_letter}T' if var_letter == 'A' else 'AT'
        if kind == 'element':
            return f'{var_letter}E'
        return ''

    # Control valves: take the variable letter from any signal-connected
    # controller / transmitter and append "CV".
    if kind == 'valve':
        nbr_tag = _first_neighbour_tag(node, all_nodes, edges, signal_only=True)
        if nbr_tag:
            var = _prefix_of(nbr_tag)[:1]
            if var:
                return f'{var}CV'
        return ''
    return ''


def _first_neighbour_tag(node: dict, all_nodes: List[dict],
                         edges: List[dict], signal_only: bool = False) -> str:
    nid = node.get('id')
    if not nid:
        return ''
    by_id = {n.get('id'): n for n in all_nodes}
    for e in edges:
        if signal_only and (e.get('connType') or e.get('kind')) != 'signal':
            continue
        other_id = None
        if e.get('from') == nid:
            other_id = e.get('to')
        elif e.get('to') == nid:
            other_id = e.get('from')
        if not other_id:
            continue
        nb = by_id.get(other_id)
        if not nb:
            continue
        tag = nb.get('tag') or nb.get('label') or ''
        if tag:
            return tag
    return ''


def _tags_in_area(all_nodes: List[dict], area: str, prefix: str,
                  known_tags: Iterable[str]) -> List[str]:
    """All known tags that share `prefix` and live in `area`."""
    pfx = prefix.upper()
    out: List[str] = []
    for n in all_nodes:
        if (n.get('area') or '') != area:
            continue
        tag = (n.get('tag') or n.get('label') or '').strip()
        if not tag:
            continue
        if _prefix_of(tag) == pfx and tag in known_tags:
            out.append(tag)
    return out


def _next_loop_number(same_area_tags: List[str], area: str,
                      all_nodes: List[dict], prefix: str,
                      known_tags: Iterable[str]) -> Optional[int]:
    """Find the next free loop number for `prefix`, preferring a gap in the
    same-area sequence; otherwise area-prefix + next free across the plant."""
    nums = sorted({_digits_of(t) for t in same_area_tags if _digits_of(t) is not None})

    if nums:
        # Look for the smallest internal gap.
        for i in range(len(nums) - 1):
            if nums[i + 1] - nums[i] >= 2:
                return nums[i] + 1
        # No gaps — append after the highest.
        return nums[-1] + 1

    # No same-area tags for this prefix. Use the dominant 2-digit area prefix
    # of OTHER tags in the same area as the area number; failing that,
    # 999 + smallest free.
    area_prefix = _area_number_prefix(all_nodes, area, known_tags)
    used: set = set()
    for t in known_tags:
        if _prefix_of(t) == prefix.upper():
            d = _digits_of(t)
            if d is not None:
                used.add(d)
    if area_prefix is not None:
        # Try area_prefix * 100 + 01..99
        for offset in range(1, 100):
            candidate = area_prefix * 100 + offset
            if candidate not in used:
                return candidate
    # Last resort
    base = 999
    while base in used:
        base += 1
    return base


def _area_number_prefix(all_nodes: List[dict], area: str,
                        known_tags: Iterable[str]) -> Optional[int]:
    """Dominant 2-digit numeric prefix among known tags in `area` (e.g. CTP's
    H2 FEED → 10, CO2 FEED → 10/11, etc.). Returns None if undetermined."""
    counter: Counter = Counter()
    for n in all_nodes:
        if (n.get('area') or '') != area:
            continue
        tag = (n.get('tag') or n.get('label') or '').strip()
        if tag in known_tags:
            d = _digits_of(tag)
            if d is None:
                continue
            digits_str = str(d)
            if len(digits_str) >= 3:
                counter[int(digits_str[:2])] += 1
    if not counter:
        return None
    return counter.most_common(1)[0][0]


# ── run_tag_inference ─────────────────────────────────────────────────────────

def run_tag_inference(nodes: List[dict], edges: List[dict]) -> List[dict]:
    """Top-level entry — iterate every node and emit proposals.

    Skips nodes whose existing tag passes is_valid_isa_tag.
    Calls infer_tag for nodes with no tag, normalize_tag for nodes with a tag
    that fails validation. The returned proposal carries the originating
    node_id and original tag so a caller can apply it without re-walking nodes.
    """
    # Build the "known tags" set once — only canonically-shaped tags
    # participate in fuzzy matching and gap detection. (engine.is_valid_isa_tag
    # is too permissive for this use; line-number-style strings like
    # 'RV-4502-1' would otherwise pollute the corpus.)
    known_tags: set = set()
    for n in nodes:
        tag = (n.get('tag') or n.get('label') or '').strip()
        kind = (n.get('kind') or '').lower()
        if tag and _is_clean_tag(tag, kind):
            known_tags.add(tag)

    proposals: List[dict] = []
    for node in nodes:
        node_id = node.get('id')
        if not node_id:
            continue
        kind = (node.get('kind') or '').lower()
        area = node.get('area') or ''
        tag  = (node.get('tag') or node.get('label') or '').strip()

        # Placeholder tags ('HV-60XX', 'TI-30??') are unambiguous extractor
        # markers for "couldn't read the digits". Treat as unnamed and route
        # to infer_tag — fuzzy-matching them to a near-but-real tag would be
        # a guess. Force review_state='inferred' so the engineer reviews.
        is_placeholder = bool(tag) and (
            'XX' in tag or 'xx' in tag or '??' in tag
        )

        if tag and not is_placeholder and _is_clean_tag(tag, kind):
            continue  # tag already valid — nothing to do

        if is_placeholder or not tag:
            result = infer_tag(node, nodes, edges, known_tags)
            if result is not None:
                # Spec: review_state='inferred' regardless of confidence
                result = dict(result)
                result['review_state'] = 'inferred'
        else:
            result = normalize_tag(tag, area, kind, known_tags)

        if not result:
            continue

        proposals.append({
            'node_id':      node_id,
            'original_tag': tag,
            'proposed_tag': result['proposed'],
            'confidence':   result['confidence'],
            'method':       result['method'],
            'review_state': result['review_state'],
        })

    return proposals
