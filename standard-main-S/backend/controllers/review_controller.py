"""
controllers/review_controller.py — review-state and Pass 3/4 proposal endpoints

Extracted from main.py (Phase 8): request parsing, validation, service/repo
calls, and jsonify()/response construction for these routes -- moved
verbatim into per-function controller bodies. Flask route decorators,
function signatures, and endpoint names all remain in main.py unchanged;
each route body is now a one-line delegate to the matching function here.

Main.py-level names used by these bodies (module-level singletons like
PROJECTS_DIR/HUB/cache_store/llm/skill_registry, and the thin repository/
service wrapper functions established in Phases 2-7) are pulled in via a
function-local `import main as _m` -- mirroring the pre-existing lazy-import
pattern already used elsewhere in this codebase (api/detect.py, extract_cli.py)
to reach main.py without a module-level circular import (main.py imports
this controller module at startup).
"""
from __future__ import annotations

from flask_compat import jsonify, request

def get_review(pid):
    import main as _m
    _db_get_review = _m._db_get_review
    """Return full review state for a project. DB-backed."""
    try:
        return jsonify(_db_get_review(pid))
    except Exception:
        return jsonify({})


def update_review(pid, tag):
    import main as _m
    _db_write_review = _m._db_write_review
    load_espx = _m.load_espx
    action = request.json.get('action', 'accepted')
    espx, espx_path = load_espx(pid)
    if espx.get('studio') is None:
        espx['studio'] = {
            'metadata': {}, 'instruments': {}, 'equipment': {},
            'connections': [], 'screens': [], 'review': {}
        }
    if espx['studio'].get('review') is None:
        espx['studio']['review'] = {}
    espx['studio']['review'][tag] = action
    # DB is now the only review-state store — no review.json mirror.
    try:
        _db_write_review(pid, tag, action)
    except Exception as e:
        print(f'review DB write failed for {pid}/{tag}: {e}')
    return jsonify({'tag': tag, 'action': action})


def get_tag_proposals(pid):
    import main as _m
    load_espx = _m.load_espx
    try:
        espx, _ = load_espx(pid)
    except Exception:
        return jsonify([])
    out = []
    for n in espx.get('nodes', []) or []:
        prop = n.get('_tag_proposal')
        if not prop:
            continue
        out.append({
            'node_id':      n.get('id'),
            'original_tag': prop.get('original_tag', n.get('label', '')),
            'proposed_tag': prop.get('proposed_tag', ''),
            'confidence':   prop.get('confidence', 0),
            'method':       prop.get('method', ''),
            'review_state': prop.get('review_state', 'uncertain'),
        })
    return jsonify(out)


def update_tag_proposal(pid, node_id):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    _record_proposal_rejection = _m._record_proposal_rejection
    load_espx = _m.load_espx
    rebuild_espx_from_cache = _m.rebuild_espx_from_cache
    action = (request.json or {}).get('action', '')
    if action not in ('accept', 'reject'):
        return jsonify({'error': "action must be 'accept' or 'reject'"}), 400
    espx, espx_path = load_espx(pid)
    target = next((n for n in espx.get('nodes', []) if n.get('id') == node_id), None)
    if target is None or '_tag_proposal' not in target:
        return jsonify({'error': 'no proposal for that node'}), 404
    prop = target['_tag_proposal']
    if action == 'accept':
        new_tag = prop.get('proposed_tag') or target.get('label', '')
        target['label'] = new_tag
        if 'tag' in target:
            target['tag'] = new_tag
    target.pop('_tag_proposal', None)
    if action == 'reject':
        # Persist the rejection so a future rebuild_espx_from_cache will not
        # regenerate this proposal (Pass 3 consults review.json before
        # attaching `_tag_proposal` to a node).
        _record_proposal_rejection(espx, espx_path, pid,
                                    f'_tag_rejected:{node_id}')
    else:
        _db_persist_espx(pid, espx)
    return jsonify({'ok': True, 'action': action, 'node_id': node_id})


def get_connection_proposals(pid):
    import main as _m
    load_espx = _m.load_espx
    try:
        espx, _ = load_espx(pid)
    except Exception:
        return jsonify([])
    id_to_label = {n.get('id'): (n.get('label') or n.get('id'))
                   for n in espx.get('nodes', []) or []}
    out = []
    for n in espx.get('nodes', []) or []:
        proposals = n.get('_connection_proposals') or []
        if not proposals:
            continue
        # Surface the highest-confidence proposal per node (typical case is
        # exactly one — the inference pass returns a single first-match).
        best = max(proposals, key=lambda p: p.get('confidence', 0))
        from_id = best.get('from', n.get('id'))
        to_id   = best.get('to')
        out.append({
            'node_id':      n.get('id'),
            'from_tag':     id_to_label.get(from_id, from_id),
            'to_tag':       id_to_label.get(to_id, to_id) if to_id else '',
            'confidence':   best.get('confidence', 0),
            'method':       best.get('method', ''),
            'review_state': best.get('review_state', 'inferred'),
        })
    return jsonify(out)


def update_connection_proposal(pid, node_id):
    import main as _m
    _db_persist_espx = _m._db_persist_espx
    _record_proposal_rejection = _m._record_proposal_rejection
    load_espx = _m.load_espx
    rebuild_espx_from_cache = _m.rebuild_espx_from_cache
    action = (request.json or {}).get('action', '')
    if action not in ('accept', 'reject'):
        return jsonify({'error': "action must be 'accept' or 'reject'"}), 400
    espx, espx_path = load_espx(pid)
    target = next((n for n in espx.get('nodes', []) if n.get('id') == node_id), None)
    if target is None or '_connection_proposals' not in target:
        return jsonify({'error': 'no proposal for that node'}), 404
    proposals = target.get('_connection_proposals') or []
    if action == 'accept' and proposals:
        best = max(proposals, key=lambda p: p.get('confidence', 0))
        f, t = best.get('from'), best.get('to')
        if f and t:
            existing = {(e.get('from'), e.get('to'))
                        for e in espx.get('edges', [])
                        if (e.get('kind') or e.get('connType')) == 'signal'}
            if (f, t) not in existing and (t, f) not in existing:
                espx.setdefault('edges', []).append({
                    'from':   f,
                    'to':     t,
                    'kind':   'signal',
                    'source': 'inferred:confirmed',
                })
    target.pop('_connection_proposals', None)
    target.pop('_has_connection_proposal', None)
    if action == 'reject':
        # Persist the rejection so Pass 4 won't reattach the proposal on the
        # next rebuild_espx_from_cache.
        _record_proposal_rejection(espx, espx_path, pid,
                                    f'_conn_rejected:{node_id}')
    else:
        _db_persist_espx(pid, espx)
    return jsonify({'ok': True, 'action': action, 'node_id': node_id})
