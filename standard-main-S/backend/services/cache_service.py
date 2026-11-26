"""
services/cache_service.py — cache-based espx rebuild workflow.

Extracted from main.py (Phase 6): rebuild_espx_from_cache() — moved
verbatim. This is the Pass 3/4/5 orchestration that turns a project's
pass0 cache files back into a full espx dict: it coordinates the
project repository (review-state read, bulk espx persist), the domain
loop-inference module, and three adapters (is_garbage_tag,
run_tag_inference, run_connectivity_inference) — all via their existing
lazy, in-function imports, unchanged.

`projects_dir` is an explicit parameter (this function originally closed
over main.py's PROJECTS_DIR global) — main.py keeps a thin wrapper with the
original single-argument signature (see Phase 6 Step 9).

Coordinates: repositories.project_repository, domain.loop_inference,
adapters.engine / adapters.tag_inference / adapters.connectivity_inference
(all lazily imported, exactly as before). No Flask, no direct SQL.
"""
from __future__ import annotations

import json
from pathlib import Path

from domain.loop_inference import infer_loops
from repositories.project_repository import _db_get_review, _db_persist_espx


def rebuild_espx_from_cache(pid: str, projects_dir: Path) -> dict:
    """Rebuild espx from scratch using all pass0 cache files."""
    cache_dir = projects_dir / pid / 'cache'
    espx = {
        'nodes': [], 'edges': [],
        'meta': {'mermaid': ''},
        'studio': {
            'metadata': {'plant_name': pid, 'process_type': 'generic'},
            'instruments': {}, 'equipment': {},
            'connections': [], 'screens': [], 'review': {}
        }
    }

    pass0_files = sorted(cache_dir.glob('*_pass0.json'))
    print(f'Rebuilding espx from {len(pass0_files)} cache files')
    seen_drawings: set = set()

    for f in pass0_files:
        try:
            combined = json.loads(f.read_text(encoding='utf-8'))
            new_nodes = [
                n for n in combined.get('nodes', [])
                if n.get('drawing', '') not in seen_drawings
            ]
            seen_drawings.update(
                n.get('drawing', '') for n in new_nodes if n.get('drawing')
            )
            offset = len(espx['nodes'])
            id_map = {}
            for i, node in enumerate(new_nodes):
                old_id = node['id']
                new_id = f'n{offset + i + 1}'
                id_map[old_id] = new_id
                node = dict(node)
                node['id'] = new_id
                espx['nodes'].append(node)

            for edge in combined.get('edges', []):
                e = dict(edge)
                e['from'] = id_map.get(e['from'], e['from'])
                e['to']   = id_map.get(e['to'],   e['to'])
                espx['edges'].append(e)

            import re as _re
            from adapters.engine import is_garbage_tag
            _tag_chars = _re.compile(r'^[A-Za-z][A-Za-z0-9\-_]{0,29}$')
            # Valve and instrument prefixes that should never appear in equipment
            _valve_instr_pfx = {
                'CV', 'FV', 'LV', 'PV', 'TV', 'HV', 'XV', 'SV', 'WV', 'IV',
                'PSV', 'PRV', 'RV', 'CK', 'NRV', 'PCV', 'TCV', 'LCV', 'FCV',
                'ACV', 'HCV', 'BDV', 'SDV', 'MOV', 'AOV', 'ROV', 'GOV', 'SCV',
                'FT', 'PT', 'TT', 'LT', 'AT', 'DT', 'ST', 'WT',
                'FI', 'PI', 'TI', 'LI', 'AI', 'FG', 'PG', 'TG', 'LG',
                'FR', 'PR', 'TR', 'LR', 'AR',
                'FS', 'PS', 'TS', 'LS',
                'FIC', 'PIC', 'TIC', 'LIC', 'AIC',
                'FE', 'PE', 'TE', 'LE', 'FM', 'QT',
                'FC', 'PC', 'TC', 'LC', 'AC',
            }
            studio = espx['studio']
            _accepted = 0
            _rejected_tags: list[str] = []

            for tag, data in combined.get('instruments', {}).items():
                if not _tag_chars.match(tag):
                    continue
                kind = data.get('kind', 'transmitter') if isinstance(data, dict) else 'transmitter'
                if not is_garbage_tag(tag, kind) and tag not in studio['instruments']:
                    studio['instruments'][tag] = data
                    _accepted += 1
                elif tag not in studio['instruments']:
                    _rejected_tags.append(tag)

            for tag, data in combined.get('equipment', {}).items():
                if not _tag_chars.match(tag):
                    continue
                # Skip off_page connectors
                if tag.lower().startswith('off_page'):
                    continue
                # Skip placeholder tags (X-XXX, HV-XXXX etc.)
                if _re.search(r'[Xx]{2,}', tag):
                    continue
                # Skip tags whose prefix maps to valves or instruments
                pfx = tag.split('-')[0].split('_')[0].upper()
                if pfx in _valve_instr_pfx:
                    continue
                kind = data.get('kind', 'vessel') if isinstance(data, dict) else 'vessel'
                if not is_garbage_tag(tag, kind) and tag not in studio['equipment']:
                    studio['equipment'][tag] = data
                    _accepted += 1
                elif tag not in studio['equipment']:
                    _rejected_tags.append(tag)

            print(f'  {f.name}: +{len(new_nodes)} nodes  '
                  f'(tags accepted: {_accepted}, rejected as garbage: {len(_rejected_tags)})')
            if _rejected_tags:
                sample = _rejected_tags[:10]
                print(f'    First rejected: {sample}')
        except Exception as e:
            print(f'  SKIP {f.name}: {e}')

    # Load engineer rejection ledger once — the `review` table holds
    # `_tag_rejected:<id>` / `_conn_rejected:<id>` rows written by the
    # proposal POST routes. Passes 3 and 4 consult it before attaching
    # anything so a rejected proposal does not return on rebuild.
    try:
        _review_persist = _db_get_review(pid)
    except Exception:
        _review_persist = {}
    _tag_rejected_ids = {
        k.split(':', 1)[1] for k, v in _review_persist.items()
        if k.startswith('_tag_rejected:') and v == 'rejected'
    }
    _conn_rejected_ids = {
        k.split(':', 1)[1] for k, v in _review_persist.items()
        if k.startswith('_conn_rejected:') and v == 'rejected'
    }

    # ── Pass 3: tag normalisation + inference ────────────────────────────────
    # Runs after Pass 2.5 results have been merged, before nodes are written.
    # Auto-confidence proposals are applied directly; uncertain / inferred
    # proposals are stored on the node so the engineer can review them.
    try:
        from adapters.tag_inference import run_tag_inference
        proposals = run_tag_inference(espx['nodes'], espx['edges'])
        node_by_id = {n['id']: n for n in espx['nodes']}
        n_auto = n_review = n_skipped = 0
        for p in proposals:
            n = node_by_id.get(p['node_id'])
            if not n:
                continue
            if p['review_state'] == 'auto':
                # Write the corrected tag back. espx uses 'label' canonically;
                # keep 'tag' in sync if the cache happened to populate it.
                if 'tag' in n:
                    n['tag'] = p['proposed_tag']
                n['label'] = p['proposed_tag']
                n['review_state'] = 'auto'
                n_auto += 1
            else:
                # Honour the engineer's previous rejection — do not re-attach.
                if p['node_id'] in _tag_rejected_ids:
                    n_skipped += 1
                    continue
                # Preserve the original tag — only annotate.
                n['_tag_proposal'] = p
                n['review_state']  = p['review_state']
                n_review += 1
        print(f'Pass 3 tag inference: {len(proposals)} proposals '
              f'({n_auto} auto-applied, {n_review} flagged for review, '
              f'{n_skipped} previously-rejected)')
    except Exception as e:
        print(f'Pass 3 tag inference SKIPPED: {e}')

    # ── Pass 4: signal-edge inference ────────────────────────────────────────
    # For every instrument / control valve with no signal edge, propose one.
    # Auto-confidence (equipment_ref) writes the new edge directly; uncertain
    # / inferred proposals attach to the source node under
    # `_connection_proposals` so the engineer can review them in the editor.
    try:
        from adapters.connectivity_inference import run_connectivity_inference
        result = run_connectivity_inference(
            espx['nodes'], espx['edges'], espx.get('studio', {}),
        )
        node_by_id = {n['id']: n for n in espx['nodes']}
        n_auto = n_review = n_skipped = 0
        for prop in result['proposals']:
            if prop['review_state'] == 'auto':
                espx['edges'].append({
                    'from':   prop['from'],
                    'to':     prop['to'],
                    'kind':   'signal',
                    'source': 'inferred:equipment_ref',
                })
                n_auto += 1
            else:
                src = node_by_id.get(prop['from'])
                if not src:
                    continue
                # Honour the engineer's previous rejection — do not re-attach.
                if prop['from'] in _conn_rejected_ids:
                    n_skipped += 1
                    continue
                src.setdefault('_connection_proposals', []).append(prop)
                src['_has_connection_proposal'] = True
                n_review += 1
        s = result['stats']
        print(f"Pass 4 connectivity inference: "
              f"{s['unconnected_instruments']} unconnected · "
              f"{s['proposed']} proposed "
              f"({n_auto} auto, {n_review} flagged, "
              f"{n_skipped} previously-rejected) · "
              f"by_method={s['by_method']} · "
              f"unproposeble={s['unproposeble']}")
    except Exception as e:
        print(f'Pass 4 connectivity inference SKIPPED: {e}')

    # ── Pass 5: loop inference + loop_id backfill ────────────────────────────
    # Tag-name matching infers loops (FT-101 + FIC-101 + FCV-101 → loop FIC-101).
    # Write loop_id back to both studio.instruments[tag] (existing convention)
    # and to espx['nodes'] (so downstream MCP queries can answer "what loop is
    # node X in?" without re-deriving it).
    try:
        loops = infer_loops(espx)
        instruments = espx.get('studio', {}).get('instruments', {})
        label_to_nodes: dict = {}
        for n in espx.get('nodes', []):
            lbl = (n.get('label') or '').strip().upper()
            if lbl:
                label_to_nodes.setdefault(lbl, []).append(n)
        n_node_writes = 0
        for loop_id, loop in loops.items():
            participants = []
            for role in ('measurement', 'controller', 'final_element'):
                t = loop.get(role)
                if t: participants.append(t)
            participants.extend(loop.get('indicators') or [])
            participants.extend(loop.get('alarms') or [])
            for tag in participants:
                if tag in instruments:
                    instruments[tag]['loop_id'] = loop_id
                for n in label_to_nodes.get(tag.strip().upper(), []):
                    n['loop_id'] = loop_id
                    n_node_writes += 1
        espx.setdefault('studio', {})['loops'] = loops
        print(f'Pass 5 loop inference: {len(loops)} loops, {n_node_writes} node loop_id writes')
    except Exception as e:
        print(f'Pass 5 loop inference SKIPPED: {e}')

    # ── DB persist — nodes/edges/instruments/etc. for this project ──────────
    # The DB is the system of record now; the .espx file is no longer written.
    try:
        _db_persist_espx(pid, espx)
    except Exception as e:
        print(f'rebuild_espx_from_cache DB persist failed for {pid}: {e}')

    return espx
