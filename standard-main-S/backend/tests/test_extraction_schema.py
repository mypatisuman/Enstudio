"""Phase 1: schema <-> consumer compatibility for the extraction pipeline.

The bug class this guards: prompts.py declares the JSON schema the LLM must
answer with, and extraction_cli/commands.py reads fields off that answer. The
two drifted -- commands.py read node['drawing'], ['area'], ['kind'] and
['description'] and edge['insulation'] / ['to_drawing'], none of which were
declared. Against a provider that ENFORCES the schema those fields are
stripped, so the consumer read '' on every run and multi-drawing grouping was
silently dead.

These tests read the ACTUAL source of commands.py rather than a hand-written
list, so a future field added to either side without the other is caught.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

from prompts import (  # noqa: E402
    _NODE_SCHEMA, _EDGE_SCHEMA, _JUNCTION_SCHEMA,
    CV_VERIFY_OUTPUT_SCHEMA, CV_CONNECTIONS_OUTPUT_SCHEMA,
)

_COMMANDS_SRC = (STUDIO / 'extraction_cli' / 'commands.py').read_text(encoding='utf-8')

# Fields written by our own Python after parsing, never expected FROM the LLM.
# They must not be required in the schema, and their absence is not drift.
# 'bbox_px' is the detector symbol's pixel box, stamped by
# services/geometry_store.stamp_symbol_bboxes for the connectivity export;
# it is never requested from the model.
_CODE_POPULATED_NODE = {'page', 'category', 'type', 'bbox_px'}
# 'line_indices' is read off connectivity_graph.py's GEOMETRY edges, not off
# the LLM's answer -- commands.py reuses the name `_e` for both. It is produced
# by our own geometry code and must never be requested from the model, so its
# absence from _EDGE_SCHEMA is correct, not drift.
_CODE_POPULATED_EDGE = {'waypoints', 'audited', 'line_indices'}


def _read_fields(pattern: str) -> set[str]:
    return set(re.findall(pattern, _COMMANDS_SRC))


def test_every_node_field_the_consumer_reads_is_declared():
    read = _read_fields(r"node\.get\('([a-z_]+)'") | _read_fields(r"\bn\.get\('([a-z_]+)'")
    declared = set(_NODE_SCHEMA['properties'])
    missing = read - declared - _CODE_POPULATED_NODE
    assert not missing, (
        f'commands.py reads node fields that _NODE_SCHEMA does not declare: '
        f'{sorted(missing)} — a schema-enforcing provider will strip them'
    )


def test_every_edge_field_the_consumer_reads_is_declared():
    read = _read_fields(r"edge\.get\('([a-z_]+)'") | _read_fields(r"_e\.get\('([a-z_]+)'")
    declared = set(_EDGE_SCHEMA['properties'])
    missing = read - declared - _CODE_POPULATED_EDGE - {'from', 'to'}
    assert not missing, (
        f'commands.py reads edge fields that _EDGE_SCHEMA does not declare: '
        f'{sorted(missing)}'
    )


def test_no_declared_field_is_entirely_unconsumed():
    """Drift in the other direction: a field we pay output tokens for and
    never read. 'segments' is consumed in llm_verification.py, so that file
    counts as a consumer too."""
    llm_src = (STUDIO / 'extraction_cli' / 'llm_verification.py').read_text(encoding='utf-8')
    both = _COMMANDS_SRC + llm_src
    for field in _NODE_SCHEMA['properties']:
        assert f"'{field}'" in both, f'_NODE_SCHEMA declares {field!r} but nothing reads it'
    for field in _EDGE_SCHEMA['properties']:
        assert f"'{field}'" in both, f'_EDGE_SCHEMA declares {field!r} but nothing reads it'


def test_edge_kind_enum_matches_the_prompt_text():
    """The enum and the instruction the model is given must agree; if they
    drift the model is told to emit a value the schema then rejects."""
    prompt_src = (STUDIO / 'prompts.py').read_text(encoding='utf-8')
    enum = _EDGE_SCHEMA['properties']['kind']['enum']
    assert enum == ['process', 'signal', 'pneumatic']
    m = re.search(r'Edge "kind" is one of: ([^\n]+)', prompt_src)
    assert m, 'prompt no longer states the allowed edge kinds'
    stated = set(re.findall(r'"([a-z]+)"', m.group(1)))
    assert stated == set(enum), f'prompt says {sorted(stated)}, schema says {sorted(enum)}'


def test_process_kinds_consumer_is_a_superset_of_the_enum():
    """Every kind the model may emit must be classifiable by the consumer as
    piping-or-not. A kind in the enum but missing from both branches would be
    silently dropped from the connections table."""
    m = re.search(r'process_kinds = \{([^}]*)\}', _COMMANDS_SRC)
    assert m, 'process_kinds set not found in commands.py'
    process_kinds = set(re.findall(r"'([a-z_]+)'", m.group(1)))
    assert 'process' in process_kinds
    # signal/pneumatic are deliberately NOT piping.
    assert 'signal' not in process_kinds
    assert 'pneumatic' not in process_kinds


def test_required_fields_are_all_declared():
    for schema in (_NODE_SCHEMA, _EDGE_SCHEMA, _JUNCTION_SCHEMA):
        for req in schema.get('required', []):
            assert req in schema['properties'], f'{req!r} required but not declared'


def test_top_level_output_schemas_are_wellformed():
    assert CV_VERIFY_OUTPUT_SCHEMA['required'] == ['nodes']
    assert set(CV_CONNECTIONS_OUTPUT_SCHEMA['required']) == {'junctions', 'edges'}
    # drawing.number is what _extract_one_page now reads for page identity.
    drawing = CV_VERIFY_OUTPUT_SCHEMA['properties']['drawing']
    assert 'number' in drawing['properties']


def test_drawing_number_is_actually_consumed():
    """Regression for the specific drift this phase fixed: the schema declared
    a top-level drawing block that no code path read."""
    assert "_drw.get('number')" in _COMMANDS_SRC or "'number'" in _COMMANDS_SRC, \
        'drawing.number is declared in the schema but read by nothing'


def test_commands_module_parses():
    ast.parse(_COMMANDS_SRC)
