"""
adapters/engine/__init__.py — public API surface for the engine package.

Phase 10: adapters/engine.py (~1724 lines) was decomposed into this package:

    constants.py       lookup tables, mapping dicts, compiled regexes
    tag_normalizer.py  tag quality checks, ISA-5.1 decode, garbage filtering,
                        instrument-type normalization
    node_builder.py    node classification (classify_node) + bbox derivation
    parser.py          YMPL-schema loading + YMPL-doc -> internal model
    graph_builder.py   Perry's-pattern sequencing/completeness + the 5-step
                        connectivity inference pipeline
    exporter.py         internal model -> VIDS YAML export

Every name that used to be importable via `from adapters.engine import X`
is re-exported here unchanged, so no downstream caller needs to change —
this module re-exports the *complete* original attribute surface (including
underscore-prefixed names that turned out to be imported externally, e.g.
`_extract_prefix`/`_check_tag_quality` by controllers/project_controller.py)
rather than only the small subset with confirmed external callers, so any
caller this audit missed keeps working too.
"""
from __future__ import annotations

from .constants import (
    SCHEMA_DIR, INSTRUMENT_KINDS, PROCESS_KINDS, MECHANICAL_KINDS,
    CONNECTOR_KINDS, ALL_KINDS, ANNOTATION_BLACKLIST,
    _RE_LINE_DESIG, _RE_DRAWING_NO, _GARBAGE_PFXS,
    _ISA_MEASURED_VAR, _ISA_FUNCTION_MAP, _SAFETY_VALVE_PREFIXES,
    _MECHANICAL_VALVE_PREFIXES, _KIND_TO_CLASS,
    _DESCRIPTION_WORDS, _DESCRIPTION_PHRASES, _DCS_ABBREVIATIONS,
    _NON_PHYSICAL_STARTS, _NON_PHYSICAL_ALARM_SUFFIXES,
    _PERRY_PATTERNS, _AREA_KW, _PAT_KINDS, _REQUIRED, _PALETTE_TO_CANON,
    _INFER_AREA_ORDER, _TAG_DIGIT_RANK,
)
from .tag_normalizer import (
    _is_physical, _check_tag_quality, _extract_prefix, _isa_decode,
    is_garbage_tag, is_valid_isa_tag, test_garbage_filter,
    normalize_instrument_type,
)
from .node_builder import (
    derive_bbox, classify_node, _classify_node_core, _merge_instrument,
)
from .parser import (
    load_schema, ympl_to_internal, _infer_loops,
)
from .graph_builder import (
    verify_and_sequence, _infer_area_rank, _node_area_rank, infer_connections,
)
from .exporter import export_vids

__all__ = [
    'SCHEMA_DIR', 'INSTRUMENT_KINDS', 'PROCESS_KINDS', 'MECHANICAL_KINDS',
    'CONNECTOR_KINDS', 'ALL_KINDS', 'ANNOTATION_BLACKLIST',
    '_RE_LINE_DESIG', '_RE_DRAWING_NO', '_GARBAGE_PFXS',
    '_ISA_MEASURED_VAR', '_ISA_FUNCTION_MAP', '_SAFETY_VALVE_PREFIXES',
    '_MECHANICAL_VALVE_PREFIXES', '_KIND_TO_CLASS',
    '_DESCRIPTION_WORDS', '_DESCRIPTION_PHRASES', '_DCS_ABBREVIATIONS',
    '_NON_PHYSICAL_STARTS', '_NON_PHYSICAL_ALARM_SUFFIXES',
    '_is_physical', '_check_tag_quality', '_extract_prefix', '_isa_decode',
    'derive_bbox', 'classify_node', '_classify_node_core',
    'is_garbage_tag', 'is_valid_isa_tag', 'test_garbage_filter',
    '_merge_instrument', 'normalize_instrument_type',
    'load_schema', 'ympl_to_internal', '_infer_loops',
    '_PERRY_PATTERNS', '_AREA_KW', '_PAT_KINDS', '_REQUIRED', '_PALETTE_TO_CANON',
    'verify_and_sequence', '_INFER_AREA_ORDER', '_infer_area_rank',
    '_TAG_DIGIT_RANK', '_node_area_rank', 'infer_connections',
    'export_vids',
]
