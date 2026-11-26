"""tests/test_convert.py — unit tests for ympl_parser.convert.vids_to_ympl"""
import pytest
from typer.testing import CliRunner

from ympl_parser.convert import vids_to_ympl
from cli.enable import app

runner = CliRunner()

# ── Shared fixture ─────────────────────────────────────────────────────────────

SAMPLE_VIDS = {
    'equipment': {
        'R-301':  {'type': 'reactor',        'area': 'Reactors', 'description': ''},
        'HE-302': {'type': 'heat_exchanger', 'area': 'Reactors', 'description': ''},
        'P-601':  {'type': 'pump',           'area': 'Dosing',   'description': ''},
    },
    'instruments': {
        'FT-101':  {'type': 'transmitter', 'equipment_ref': 'P-601',
                    'range_hi': 500.0,     'units': 'kg/h'},
        'FIC-101': {'type': 'controller',  'equipment_ref': 'P-601'},
    },
    'connections': [
        # process → process (should be included)
        {'from_tag': 'P-601',  'to_tag': 'R-301',  'id': 'S-001', 'type': 'process'},
        {'from_tag': 'R-301',  'to_tag': 'HE-302', 'id': 'S-002', 'type': 'process',
         'fluid': 'reactor effluent'},
        # instrument endpoint (should be filtered)
        {'from_tag': 'P-601',  'to_tag': 'FT-101', 'id': 'P-601 outlet', 'type': 'process'},
        # valve endpoint (should be filtered)
        {'from_tag': 'R-301',  'to_tag': 'HV-001', 'id': 'S-003', 'type': 'process'},
        # duplicate (should be deduplicated)
        {'from_tag': 'P-601',  'to_tag': 'R-301',  'id': 'S-001-dup', 'type': 'process'},
    ],
    'metadata': {
        'plant_name': 'Test Plant',
        'revision':   2,
        'date':       '2026-04-19',
        'changelog':  [],
    },
}


@pytest.fixture
def result():
    return vids_to_ympl(SAMPLE_VIDS)


# ── Test 1: equipment becomes nodes ───────────────────────────────────────────

def test_equipment_becomes_nodes(result):
    labels = {n['label'] for n in result['nodes']}
    assert 'R-301'  in labels
    assert 'HE-302' in labels
    assert 'P-601'  in labels
    assert len(result['nodes']) == 3


def test_node_kind_preserved(result):
    kinds = {n['label']: n['kind'] for n in result['nodes']}
    assert kinds['R-301']  == 'reactor'
    assert kinds['HE-302'] == 'heat_exchanger'
    assert kinds['P-601']  == 'pump'


# ── Test 2: connections filtered to process-to-process only ───────────────────

def test_process_to_process_connections_only(result):
    # Only S-001 (P-601 → R-301) and S-002 (R-301 → HE-302) survive
    assert len(result['edges']) == 2


def test_instrument_endpoint_filtered(result):
    node_ids = {n['id'] for n in result['nodes']}
    for edge in result['edges']:
        assert edge['from'] in node_ids
        assert edge['to']   in node_ids


def test_duplicate_edge_deduplicated(result):
    pairs = [(e['from'], e['to']) for e in result['edges']]
    assert len(pairs) == len(set(pairs))


def test_edge_fluid_preserved(result):
    labels = {n['id']: n['label'] for n in result['nodes']}
    fluid_edge = next(
        e for e in result['edges']
        if labels[e['from']] == 'R-301' and labels[e['to']] == 'HE-302'
    )
    assert fluid_edge.get('fluid') == 'reactor effluent'


# ── Test 3: topology_ref matches node id ──────────────────────────────────────

def test_topology_ref_matches_node_id(result):
    label_to_id = {n['label']: n['id'] for n in result['nodes']}
    for tag, eq in result['enable']['equipment'].items():
        assert eq['topology_ref'] == label_to_id[tag], \
            f'{tag}: topology_ref {eq["topology_ref"]} != node id {label_to_id[tag]}'


def test_topology_refs_unique(result):
    refs = [eq['topology_ref'] for eq in result['enable']['equipment'].values()]
    assert len(refs) == len(set(refs)), 'topology_ref collision'


def test_equipment_type_mapped(result):
    assert result['enable']['equipment']['R-301']['type']  == 'reactor'
    assert result['enable']['equipment']['HE-302']['type'] == 'heat_exchanger'
    assert result['enable']['equipment']['P-601']['type']  == 'pump'


# ── Test 4: instruments preserved ─────────────────────────────────────────────

def test_instruments_preserved(result):
    instr = result['enable']['instruments']
    assert 'FT-101'  in instr
    assert 'FIC-101' in instr


def test_instrument_fields(result):
    ft = result['enable']['instruments']['FT-101']
    assert ft['type']          == 'transmitter'
    assert ft['equipment_ref'] == 'P-601'
    assert ft['range_hi']      == 500.0
    assert ft['units']         == 'kg/h'


def test_instrument_without_range(result):
    fic = result['enable']['instruments']['FIC-101']
    assert fic['type'] == 'controller'
    assert 'range_hi' not in fic


# ── Test 5: schema fields ──────────────────────────────────────────────────────

def test_schema_version(result):
    assert result['schema_version'] == 'ympl-1.0'


def test_id_slugified(result):
    assert result['id'] == 'test_plant'
    assert result['title'] == 'Test Plant'


def test_meta_revision(result):
    assert result['meta']['vids_revision'] == 2


# ── Test 6: CLI --vids exits 0 ────────────────────────────────────────────────

def test_cli_vids_flag(tmp_path):
    import yaml
    vids_file = tmp_path / 'sample_vids.yaml'
    out_file  = tmp_path / 'out.ympl'
    vids_file.write_text(yaml.dump(SAMPLE_VIDS), encoding='utf-8')

    result = runner.invoke(app, ['convert', str(vids_file), '--vids', '--out', str(out_file)])
    assert result.exit_code == 0, result.output
    assert out_file.exists()

    loaded = yaml.safe_load(out_file.read_text(encoding='utf-8'))
    assert loaded['schema_version'] == 'ympl-1.0'
    assert len(loaded['nodes']) == 3


def test_cli_missing_file_exits_1():
    result = runner.invoke(app, ['convert', 'nonexistent.yaml', '--vids'])
    assert result.exit_code == 1
