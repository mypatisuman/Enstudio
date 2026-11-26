"""Phase 1 end-to-end: a real multi-page PDF through run_extraction, checked
in the database.

This is the test that would have caught the original bug. CV and both LLM
stages are mocked (no network, no GPU, no weights); everything else is the
real pipeline — real PDF rendering, real id scoping, real _merge, real
sqlite writes, real _db_persist_espx.

Also covers the >2000-edge path end to end, and the LLM-B failure path
producing PARTIAL rather than a silently empty, "successful" extraction.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

STUDIO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(STUDIO))

fitz = pytest.importorskip('fitz', reason='PyMuPDF needed to build test PDFs')


# --------------------------------------------------------------------------
# Fixtures: a throwaway hub + DB, and `main` imported against it.
# --------------------------------------------------------------------------

# This module owns its studio.db: the `hub` fixture below is module-scoped and
# seeds the settings table once. Opt out of conftest's autouse per-test DB
# isolation, which would otherwise re-point adapters.db after `hub` ran and
# throw away the seeded provider key.
pytestmark = pytest.mark.own_db


@pytest.fixture(scope='module')
def hub(tmp_path_factory):
    d = tmp_path_factory.mktemp('hub')
    os.environ['ENGINEERING_HUB'] = str(d)
    os.environ.setdefault('JWT_SECRET', 'test-only-secret')
    (d / 'projects').mkdir(parents=True, exist_ok=True)
    from adapters import db as _db
    _db.reset_for_path(d / 'studio.db')
    _db.init_db()
    # run_extraction refuses to start without a configured provider key. Seed
    # a dummy one into the throwaway settings table — no call ever reaches a
    # provider, both LLM stages are mocked.
    from adapters.config import save_config
    save_config({'llm_provider': 'anthropic', 'anthropic_api_key': 'test-key-not-real'})
    return d


@pytest.fixture(scope='module')
def studio_main(hub):
    import main
    return main


@pytest.fixture(autouse=True)
def _emit_through_sys_stdout(monkeypatch):
    """extraction_cli.output caches sys.stdout.buffer at import time, so under
    pytest's capture that handle is already closed. Point emit() at the
    text-mode sys.stdout instead — the real emit() code path still runs, we
    just take the branch capsys can see."""
    import extraction_cli.output as out
    monkeypatch.setattr(out, '_stdout_buf', None)


def _make_pdf(path: Path, n_pages: int, sizes=None):
    doc = fitz.open()
    for i in range(n_pages):
        w, h = (sizes[i] if sizes else (800, 600))
        page = doc.new_page(width=w, height=h)
        page.draw_line(fitz.Point(10, 10), fitz.Point(w - 10, h - 10))
    doc.save(str(path))
    doc.close()
    return path


# --------------------------------------------------------------------------
# Mock CV + LLM. Each page yields two symbols and one edge between them, with
# ids that COLLIDE across pages on purpose ("n1"/"n2" every time).
# --------------------------------------------------------------------------

def _install_mocks(monkeypatch, *, n_edges=1, llm_b_fails=False):
    import extraction_cli.commands as cmds

    def fake_run_full_cv(image_bytes, base_name, cache_dir, img_w=0, img_h=0,
                         on_text_done=None):
        symbols = [
            {'bbox': [10, 10, 50, 50], 'type': 'Vessel', 'score': 0.9},
            {'bbox': [200, 10, 240, 50], 'type': 'Pump', 'score': 0.9},
        ]
        if on_text_done:
            on_text_done({'texts': []}, symbols, 800, 600)
        return {
            'symbols': symbols, 'texts': [], 'lines': [],
            'image_size': {'width': 800, 'height': 600},
            'symbol_image': '', 'sym_error': None,
            'text_error': None, 'line_error': None,
        }

    class _Resp:
        input_tokens, output_tokens, cost_usd = 5, 7, 0.0001
        model, provider = 'mock', 'mock'

    def fake_llm_a(_s, image_bytes, media_type, cv_summary_text,
                   img_w, img_h, raw_lines):
        nodes = [
            {'id': 'n1', 'type': 'Vessel', 'kind': 'vessel', 'category': 'equipment',
             'label': 'V-1', 'x': 0.1, 'y': 0.1, 'confidence': 0.9},
            {'id': 'n2', 'type': 'Pump', 'kind': 'pump', 'category': 'equipment',
             'label': 'P-1', 'x': 0.5, 'y': 0.1, 'confidence': 0.9},
        ]
        for i in range(3, 3 + max(0, n_edges - 1)):
            nodes.append({'id': f'n{i}', 'type': 'Pump', 'kind': 'pump',
                          'category': 'equipment', 'label': f'P-{i}',
                          'x': 0.5, 'y': 0.1, 'confidence': 0.9})
        return {'nodes': nodes,
                'drawing': {'number': '', 'title': ''}}, _Resp()

    def fake_llm_b(_s, image_bytes, media_type, conn_summary_text,
                   proposed_graph_text=''):
        if llm_b_fails:
            from extraction_cli.llm_verification import LlmStageError
            raise LlmStageError('llm_b_connections', 'mocked failure')
        edges = [{'from': 'n1', 'to': 'n2', 'kind': 'process'}]
        for i in range(3, 3 + max(0, n_edges - 1)):
            edges.append({'from': 'n2', 'to': f'n{i}', 'kind': 'process'})
        return {'edges': edges, 'junctions': []}, _Resp()

    monkeypatch.setattr(cmds, '_run_full_cv', fake_run_full_cv)
    monkeypatch.setattr(cmds, '_call_llm_verification', fake_llm_a)
    monkeypatch.setattr(cmds, '_call_llm_connections', fake_llm_b)


def _events(capsys):
    out, _ = capsys.readouterr()
    evs = []
    for line in out.splitlines():
        line = line.strip()
        if line.startswith('{'):
            try:
                evs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return evs


def _done(evs):
    return next((e for e in evs if e.get('stage') == 'done'), None)


def _db_rows(hub, pid):
    from adapters import db as _db
    conn = _db.get_db()
    nodes = conn.execute('SELECT id, label, extra_json FROM nodes WHERE pid=?', (pid,)).fetchall()
    edges = conn.execute('SELECT from_id, to_id FROM edges WHERE pid=?', (pid,)).fetchall()
    return nodes, edges


# --------------------------------------------------------------------------
# Tests
# --------------------------------------------------------------------------

def test_single_page_pdf_yields_one_page_and_unprefixed_ids(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch)
    pdf = _make_pdf(tmp_path / 'one.pdf', 1)

    run_extraction(hub, 'single', pdf)
    done = _done(_events(capsys))

    assert done is not None
    assert done['status'] == 'SUCCESS'
    assert done['total_pages'] == 1
    nodes, edges = _db_rows(hub, 'single')
    ids = sorted(r['id'] for r in nodes)
    assert ids == ['n1', 'n2'], 'single-page ids must stay exactly as before'
    assert len(edges) == 1


def test_three_page_pdf_yields_three_pages_and_no_id_collision(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """The headline regression. Every page produces 'n1'/'n2'; without
    scoping the (id,pid)-keyed nodes table keeps only the last page."""
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch)
    pdf = _make_pdf(tmp_path / 'three.pdf', 3)

    run_extraction(hub, 'triple', pdf)
    evs = _events(capsys)
    done = _done(evs)

    assert done['status'] == 'SUCCESS'
    assert done['total_pages'] == 3

    nodes, edges = _db_rows(hub, 'triple')
    assert len(nodes) == 6, f'3 pages x 2 nodes, got {len(nodes)}'
    assert len(edges) == 3, f'3 pages x 1 edge, got {len(edges)}'

    ids = sorted(r['id'] for r in nodes)
    assert ids == ['p1_n1', 'p1_n2', 'p2_n1', 'p2_n2', 'p3_n1', 'p3_n2']
    assert len(set(ids)) == len(ids), 'ids collided across pages'


def test_page_number_and_drawing_survive_into_the_database(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch)
    pdf = _make_pdf(tmp_path / 'pages.pdf', 3)

    run_extraction(hub, 'pagemeta', pdf)
    _events(capsys)

    nodes, _ = _db_rows(hub, 'pagemeta')
    extras = [json.loads(r['extra_json'] or '{}') for r in nodes]
    pages = sorted({e.get('page') for e in extras})
    drawings = sorted({e.get('drawing') for e in extras})
    assert pages == [1, 2, 3], f'page numbers lost: {pages}'
    assert drawings == ['page_1', 'page_2', 'page_3'], \
        f'each page needs its own drawing identity, got {drawings}'


def test_pages_keep_independent_dimensions(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch)
    pdf = _make_pdf(tmp_path / 'mixed.pdf', 3,
                    sizes=[(1000, 400), (400, 1000), (700, 700)])

    run_extraction(hub, 'mixed', pdf)
    done = _done(_events(capsys))

    reported = {p['page']: (p['width'], p['height']) for p in done['pages']}
    assert len(reported) == 3
    ratios = [round(w / h, 2) for w, h in reported.values()]
    assert len(set(ratios)) == 3, f'page aspect ratios were flattened: {ratios}'


def test_more_than_2000_edges_all_reach_the_database(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """No LIMIT anywhere in the write or read path may drop real topology."""
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch, n_edges=2500)
    pdf = _make_pdf(tmp_path / 'big.pdf', 1)

    run_extraction(hub, 'bigproj', pdf)
    done = _done(_events(capsys))

    assert done['status'] == 'SUCCESS'
    assert done['total_connections'] == 2500
    _, edges = _db_rows(hub, 'bigproj')
    assert len(edges) == 2500, f'expected 2500 edges in the DB, found {len(edges)}'


def test_llm_b_failure_is_partial_not_success(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """The other headline regression: an LLM-B failure used to yield edges=[]
    and a run that still looked successful."""
    from extraction_cli.commands import run_extraction
    _install_mocks(monkeypatch, llm_b_fails=True)
    pdf = _make_pdf(tmp_path / 'degraded.pdf', 1)

    run_extraction(hub, 'degraded', pdf)
    done = _done(_events(capsys))

    assert done['status'] == 'PARTIAL', 'must never report SUCCESS'
    assert done['reason'] == 'LLM_VERIFICATION_FAILED'
    # CV + LLM-A output is preserved rather than discarded.
    nodes, _ = _db_rows(hub, 'degraded')
    assert len(nodes) == 2, 'valid CV/LLM-A results must survive a PARTIAL run'


def test_llm_b_failure_on_one_page_does_not_lose_the_others(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """Per-page isolation: page 2 failing must not discard pages 1 and 3."""
    import extraction_cli.commands as cmds
    from extraction_cli.commands import run_extraction
    from extraction_cli.llm_verification import LlmStageError
    _install_mocks(monkeypatch)

    calls = {'n': 0}
    real_b = cmds._call_llm_connections

    def flaky_b(*a, **k):
        calls['n'] += 1
        if calls['n'] == 2:
            raise LlmStageError('llm_b_connections', 'mocked page-2 failure')
        return real_b(*a, **k)

    monkeypatch.setattr(cmds, '_call_llm_connections', flaky_b)
    pdf = _make_pdf(tmp_path / 'mixedstatus.pdf', 3)

    run_extraction(hub, 'mixedstatus', pdf)
    done = _done(_events(capsys))

    assert done['status'] == 'PARTIAL'
    statuses = {p['page']: p['status'] for p in done['pages']}
    assert statuses == {1: 'SUCCESS', 2: 'PARTIAL', 3: 'SUCCESS'}
    nodes, _ = _db_rows(hub, 'mixedstatus')
    assert len(nodes) == 6, 'all three pages must still be persisted'


# --------------------------------------------------------------------------
# Phase 2: the geometry-first guard, exercised through the real code path.
# --------------------------------------------------------------------------

def _install_geometry_mocks(monkeypatch, llm_b_edges):
    """CV returns two symbols joined by a real detected line, so the geometric
    candidate graph is non-empty and the guard is actually in play."""
    import extraction_cli.commands as cmds

    def fake_run_full_cv(image_bytes, base_name, cache_dir, img_w=0, img_h=0,
                         on_text_done=None):
        # Two independent, fully-covered pipe runs: n1-n2 and n3-n4. Every
        # symbol is reached by a real segment, so NONE land in
        # unmatched_symbols and there are no stubs, junctions or ambiguous
        # crossings anywhere. That is what makes an LLM edge across the two
        # runs genuinely ungrounded.
        symbols = [
            {'bbox': [10, 90, 50, 130], 'type': 'Tank', 'score': 0.9},
            {'bbox': [300, 90, 340, 130], 'type': 'Pump', 'score': 0.9},
            {'bbox': [10, 400, 50, 440], 'type': 'Tank', 'score': 0.9},
            {'bbox': [300, 400, 340, 440], 'type': 'Pump', 'score': 0.9},
        ]
        if on_text_done:
            on_text_done({'texts': []}, symbols, 800, 600)
        return {
            'symbols': symbols, 'texts': [],
            'lines': [
                {'x1': 50.0, 'y1': 110.0, 'x2': 300.0, 'y2': 110.0,
                 'direction': 'horizontal', 'kind': 'process'},
                {'x1': 50.0, 'y1': 420.0, 'x2': 300.0, 'y2': 420.0,
                 'direction': 'horizontal', 'kind': 'process'},
            ],
            'image_size': {'width': 800, 'height': 600},
            'symbol_image': '', 'sym_error': None,
            'text_error': None, 'line_error': None,
        }

    class _R:
        input_tokens, output_tokens, cost_usd = 1, 1, 0.0
        model, provider = 'mock', 'mock'

    def fake_llm_a(_s, image_bytes, media_type, cv_summary_text,
                   img_w, img_h, raw_lines):
        return {'nodes': [
            {'id': 'n1', 'type': 'Tank', 'kind': 'vessel', 'category': 'equipment',
             'label': 'V-1', 'x': 0.04, 'y': 0.18, 'confidence': 0.9},
            {'id': 'n2', 'type': 'Pump', 'kind': 'pump', 'category': 'equipment',
             'label': 'P-1', 'x': 0.40, 'y': 0.18, 'confidence': 0.9},
            {'id': 'n3', 'type': 'Tank', 'kind': 'vessel', 'category': 'equipment',
             'label': 'V-2', 'x': 0.04, 'y': 0.70, 'confidence': 0.9},
            {'id': 'n4', 'type': 'Pump', 'kind': 'pump', 'category': 'equipment',
             'label': 'P-2', 'x': 0.40, 'y': 0.70, 'confidence': 0.9},
        ], 'drawing': {'number': '', 'title': ''}}, _R()

    def fake_llm_b(_s, image_bytes, media_type, conn_summary_text,
                   proposed_graph_text=''):
        return {'edges': list(llm_b_edges), 'junctions': []}, _R()

    monkeypatch.setattr(cmds, '_run_full_cv', fake_run_full_cv)
    monkeypatch.setattr(cmds, '_call_llm_verification', fake_llm_a)
    monkeypatch.setattr(cmds, '_call_llm_connections', fake_llm_b)


def test_geometry_backed_edge_survives_and_is_marked(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    from extraction_cli.commands import run_extraction
    _install_geometry_mocks(monkeypatch, [
        {'from': 'n1', 'to': 'n2', 'kind': 'process'},
        {'from': 'n3', 'to': 'n4', 'kind': 'process'},
    ])
    run_extraction(hub, 'prov_keep', _make_pdf(tmp_path / 'k.pdf', 1))
    _events(capsys)

    from adapters import db as _db
    rows = _db.get_db().execute(
        'SELECT from_id, to_id, extra_json FROM edges WHERE pid=?', ('prov_keep',)
    ).fetchall()
    assert len(rows) == 2
    provs = {json.loads(r['extra_json'] or '{}').get('provenance') for r in rows}
    assert provs == {'geometry'}


def test_ungrounded_llm_edge_is_dropped_end_to_end(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """n1 and n4 are each already covered by their own detected pipe run, so
    neither is an unmatched symbol nor an open stub, and there is no junction
    or ambiguous crossing between them. Geometry therefore DID look at that
    pair and found nothing; an LLM edge across it is invented."""
    from extraction_cli.commands import run_extraction
    _install_geometry_mocks(monkeypatch, [
        {'from': 'n1', 'to': 'n2', 'kind': 'process'},     # real
        {'from': 'n3', 'to': 'n4', 'kind': 'process'},     # real
        {'from': 'n1', 'to': 'n4', 'kind': 'process'},     # invented
    ])
    run_extraction(hub, 'prov_drop', _make_pdf(tmp_path / 'd.pdf', 1))
    evs = _events(capsys)

    from adapters import db as _db
    rows = _db.get_db().execute(
        'SELECT from_id, to_id FROM edges WHERE pid=?', ('prov_drop',)
    ).fetchall()
    pairs = {(r['from_id'], r['to_id']) for r in rows}
    assert ('n1', 'n2') in pairs
    assert ('n3', 'n4') in pairs
    assert ('n1', 'n4') not in pairs, 'ungrounded LLM edge must be dropped'
    assert any('no geometric grounding' in (e.get('message') or '') for e in evs), \
        'the drop must be reported, not silent'


def test_extraction_persists_geometry_and_links_edges_to_lines(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """Geometry used to be built for the LLM audit and then discarded. A run
    with a detected pipe between two symbols must now leave the page size, the
    pipe run, the edge->line link and each symbol's pixel box in the database,
    which is what the connectivity export is built from."""
    import extraction_cli.commands as cmds
    from extraction_cli.commands import run_extraction
    from services import geometry_store as G
    _install_mocks(monkeypatch)
    real_cv = cmds._run_full_cv

    def cv_with_line(*args, **kwargs):
        out = real_cv(*args, **kwargs)
        out['lines'] = [{'x1': 50.0, 'y1': 30.0, 'x2': 200.0, 'y2': 30.0,
                         'direction': 'horizontal', 'kind': 'process'}]
        return out

    monkeypatch.setattr(cmds, '_run_full_cv', cv_with_line)
    pdf = _make_pdf(tmp_path / 'geo.pdf', 1)
    run_extraction(hub, 'geo', pdf, source_id=7)

    stored = G.load('geo')
    assert (7, 1) in stored['pages'], stored['pages']
    assert stored['pages'][(7, 1)]['width'] == 800
    assert stored['lines'] and stored['lines'][0]['points'][0] == [50.0, 30.0]
    line_id = stored['lines'][0]['id']
    assert line_id.startswith('s7_')

    from adapters import db as _db
    conn = _db.get_db()
    edge_extras = [json.loads(r[0] or '{}') for r in
                   conn.execute("SELECT extra_json FROM edges WHERE pid='geo'")]
    assert any(line_id in (e.get('line_ids') or []) for e in edge_extras), edge_extras
    node_extras = [json.loads(r[0] or '{}') for r in
                   conn.execute("SELECT extra_json FROM nodes WHERE pid='geo'")]
    assert any(n.get('bbox_px') == [10.0, 10.0, 50.0, 50.0] for n in node_extras)

    # Re-extracting the same document replaces its geometry, never duplicates it.
    run_extraction(hub, 'geo', pdf, source_id=7)
    assert G.summary('geo')['lines'] == len(stored['lines'])


def test_flow_annotations_are_saved_with_the_page_geometry_and_billed(
        hub, studio_main, monkeypatch, capsys, tmp_path):
    """The arrow/heat-trace pass runs on each page when enabled, its output lands
    in geometry_lines beside the pipe runs, and its tokens reach the done event."""
    import extraction_cli.commands as cmds
    import services.llm_flow_annotation_service as FA
    from types import SimpleNamespace
    from extraction_cli.commands import run_extraction
    from services import geometry_store as G
    _install_mocks(monkeypatch)
    monkeypatch.setenv('STUDIO_FLOW_ANNOTATIONS', 'on')
    seen = []

    def fake_annotations(_s, image_bytes):
        seen.append(len(image_bytes))
        return {'arrows': [{'tail': [60.0, 30.0], 'tip': [90.0, 30.0], 'confidence': 0.9}],
                'heat_trace': [[10.0, 60.0, 50.0, 60.0]], 'crops': 1, 'failed': 0,
                'usage': [SimpleNamespace(input_tokens=1000, output_tokens=50, cost_usd=0.25)]}

    monkeypatch.setattr(FA, 'detect_flow_annotations', fake_annotations)
    pdf = _make_pdf(tmp_path / 'ann.pdf', 2)
    run_extraction(hub, 'ann', pdf, source_id=3)

    assert len(seen) == 2 and all(seen), 'one pass per page, on the rendered raster'
    types = sorted(ln['type'] for ln in G.load('ann')['lines'])
    assert types.count('flow_arrow') == 2 and types.count('heat_trace') == 2
    done = _done(_events(capsys))
    assert done['usage']['cost_usd'] >= 0.5, done['usage']
