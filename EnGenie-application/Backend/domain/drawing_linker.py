"""
domain/drawing_linker.py — off-page-connector / cross-drawing topology logic.

Extracted from main.py (Phase 4).

extract_drawing_number() and _merge_connectors() are pure: given the
nodes/edges/label already in memory, they return a new result with no
filesystem, DB, or network access. Both print() progress/summary lines to
stdout — this is preserved verbatim (Phase 3/4 preserve every observable
behavior, including printed output) rather than stripped, but note it as a
minor purity caveat: these are otherwise side-effect-free and read no global
app state.

main.py's `link_cross_source()` is NOT moved here — it mutates its `espx`
argument in place (`espx['edges'].extend(...)`), which is a real side effect
beyond logging, so it stays in main.py. It calls extract_drawing_number()
from this module instead of a local copy.

Pure stdlib, no Flask/DB/adapters/services imports.
"""
from __future__ import annotations

import re
from collections import defaultdict


def extract_drawing_number(label: str):
    """Extract drawing number from off_page_connector label.
    Handles: off_page_157-2-130_X, off_page_965429-120-02_X, off_page_DWG-001_X
    """
    s = re.sub(r'^off_page_', '', label, flags=re.IGNORECASE)
    # Match longest hyphenated number sequence (at least one hyphen, digits on both sides)
    m = re.search(r'(\d[\d-]*\d)', s)
    if m:
        return m.group(1)
    # Fallback: first token before underscore
    parts = s.split('_')
    return parts[0] if parts and parts[0] else None


def _merge_connectors(nodes_list: list, edges_list: list):
    """Replace off_page_connector nodes with direct process edges, then remove ALL
    connector nodes from the output regardless of whether an edge was created.

    Two strategies tried in order:

    1. Return-connector pairing -- when connectors have their drawing field set
       (CTP numeric format: drawing='157-2-100', label='off_page_157-2-101').
       Two connectors that reference each other's drawing are paired and an edge
       is created between their adjacent real nodes.

    2. Tag-hint matching -- when the label encodes a target equipment tag
       (e.g. off_page_DWG2A_from_R101A -> R-101A; off_page_DWG14_R501 -> R-501).
       The connector's adjacent node is wired directly to the matched node.

    Connectors with no adjacency and no resolvable hint are dropped without an edge.
    All off_page_connector nodes are removed from the output in every case.
    """
    connector_ids = {n['id'] for n in nodes_list if n.get('kind') == 'off_page_connector'}
    if not connector_ids:
        return nodes_list, edges_list

    # adjacency: connector -> first adjacent real node
    adj: dict = {}
    for e in edges_list:
        f, t = e.get('from', ''), e.get('to', '')
        if f in connector_ids and t not in connector_ids:
            adj.setdefault(f, t)
        elif t in connector_ids and f not in connector_ids:
            adj.setdefault(t, f)

    # label parsing
    _PREFIXES = ('off_page_', 'off-page-', 'opc2_', 'opc3_', 'opc4_', 'opc_',
                 'osbl_', 'OP_', 'op_')
    _DWG_RE  = re.compile(r'^(DWG\w+?)_(.+)$', re.IGNORECASE)
    _HINT_RE = re.compile(r'^(from_|to_|from|to)', re.IGNORECASE)
    _NORM_RE = re.compile(r'[^A-Z0-9]')

    def _norm(s: str) -> str:
        return _NORM_RE.sub('', s.upper())

    def _parse(label: str):
        """Return (target_drawing, normalised_tag_hint)."""
        rest = label
        for pfx in _PREFIXES:
            if rest.lower().startswith(pfx.lower()):
                rest = rest[len(pfx):]
                break
        m = _DWG_RE.match(rest)
        if m:
            # DWG-prefix: DWG2A_from_R101A, DWG14_R501, DWG12A_to_T401
            dwg  = m.group(1).upper()
            desc = m.group(2)
            hint = _norm(_HINT_RE.sub('', desc, count=1))
            return dwg, hint
        # Numeric drawing ID (CTP): 157-2-101 -- no useful tag hint
        if rest and rest[0].isdigit():
            return rest.replace('_', '-').strip('-'), ''
        # Plain tag / keyword: R301, V401, CommonVent
        return '', _norm(_HINT_RE.sub('', rest, count=1))

    # normalised tag index for hint lookups
    tag_index: dict = {}
    for n in nodes_list:
        if n.get('kind') == 'off_page_connector':
            continue
        k = _norm(n.get('label', ''))
        if k:
            tag_index.setdefault(k, n['id'])

    def _find_hint(hint: str) -> str:
        if not hint or len(hint) < 3:
            return ''
        if hint in tag_index:
            return tag_index[hint]
        for k, nid in tag_index.items():
            if k.startswith(hint) or hint.startswith(k):
                return nid
        return ''

    # connector metadata
    conn_info: dict = {}
    for n in nodes_list:
        if n.get('kind') != 'off_page_connector':
            continue
        lbl              = n.get('label', '')
        own              = n.get('drawing', '').strip()
        target_dwg, hint = _parse(lbl)
        conn_info[n['id']] = {
            'drawing':    own,
            'target_dwg': target_dwg,
            'hint':       hint,
            'adj':        adj.get(n['id']),
        }

    # edge helpers
    new_edges: list = []
    seen: set  = {f"{e.get('from','')}|{e.get('to','')}" for e in edges_list}
    ectr = [10000]

    def _add_edge(n1: str, n2: str) -> bool:
        if not n1 or not n2 or n1 == n2:
            return False
        p, rp = f'{n1}|{n2}', f'{n2}|{n1}'
        if p in seen or rp in seen:
            return True
        seen.add(p)
        ectr[0] += 1
        new_edges.append({
            'id': f'ec{ectr[0]}', 'from': n1, 'to': n2,
            'connType': 'process',
            'line_id': '', 'fluid': '', 'line_size': '', 'line_class': '', 'insulation': '',
        })
        return True

    # Strategy 1: return-connector pairing (CTP numeric drawing IDs)
    paired: set = set()
    groups: dict = defaultdict(list)
    for cid, info in conn_info.items():
        if info['drawing'] and info['target_dwg']:
            key = tuple(sorted([info['drawing'], info['target_dwg']]))
            groups[key].append(cid)

    for key, cids in groups.items():
        if len(cids) < 2 or key[0] == key[1]:
            continue
        side_a = [c for c in cids if conn_info[c]['drawing'] == key[0]]
        side_b = [c for c in cids if conn_info[c]['drawing'] == key[1]]
        for c1, c2 in zip(side_a, side_b):
            if _add_edge(conn_info[c1]['adj'], conn_info[c2]['adj']):
                paired.update([c1, c2])

    # Strategy 2: tag-hint matching
    for cid, info in conn_info.items():
        if cid in paired:
            continue
        target_node = _find_hint(info['hint'])
        if target_node:
            adj_node = info['adj']
            if adj_node and adj_node != target_node:
                _add_edge(adj_node, target_node)

    # Always remove every off_page_connector and its stub edges
    out_nodes = [n for n in nodes_list  if n['id'] not in connector_ids]
    out_edges = [e for e in edges_list
                 if e.get('from') not in connector_ids
                 and e.get('to')   not in connector_ids]
    out_edges.extend(new_edges)
    n_hint = sum(1 for c, i in conn_info.items()
                 if c not in paired and _find_hint(i['hint']) and i['adj'])
    print(f'_merge_connectors: removed {len(connector_ids)} connectors, '
          f'created {len(new_edges)} edges '
          f'({len(paired) // 2} paired, {n_hint} tag-hint)')
    return out_nodes, out_edges
