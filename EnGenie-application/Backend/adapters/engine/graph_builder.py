"""
adapters/engine/graph_builder.py -- Perry's-pattern equipment sequencing,
completeness verification, and the 5-step post-extraction connectivity
inference pipeline.

Extracted from adapters/engine.py (Phase 10), moved verbatim.
"""
from __future__ import annotations

import re
from collections import defaultdict

from .constants import (
    PROCESS_KINDS, INSTRUMENT_KINDS, _PERRY_PATTERNS, _AREA_KW, _PAT_KINDS,
    _REQUIRED, _PALETTE_TO_CANON, _INFER_AREA_ORDER, _TAG_DIGIT_RANK,
)


def verify_and_sequence(nodes: list, edges: list, conventions=None) -> dict:
    """
    Sequence equipment per Perry's standard patterns and verify companion completeness.

    nodes  — list of classified node dicts (tag, kind, kind_canonical, area, pid_layer, id)
    edges  — list of {from, to, connType}
    Returns {sequences: {area → {pattern, flow_order, confidence}},
             completeness: {tag → {type, found, missing, score}}}
    """
    # ── Lookups ────────────────────────────────────────────────────────────────
    id_to_node: dict[str, dict] = {n['id']: n for n in nodes}

    succ: dict[str, list] = defaultdict(list)   # directed successors (process edges)
    pred: dict[str, list] = defaultdict(list)
    adj:  dict[str, set]  = defaultdict(set)    # undirected adjacency

    for e in edges:
        if e.get('connType') == 'signal':
            continue
        f, t = e.get('from', ''), e.get('to', '')
        if f and t and f in id_to_node and t in id_to_node:
            succ[f].append(t)
            pred[t].append(f)
            adj[f].add(t)
            adj[t].add(f)

    # ── Helpers ────────────────────────────────────────────────────────────────
    def _canon(n: dict) -> str:
        kc = n.get('kind_canonical', '') or n.get('kind', '')
        return _PALETTE_TO_CANON.get(kc, kc)

    def _tag_num(tag: str) -> str:
        m = re.search(r'(\d+)', tag or '')
        return m.group(1) if m else ''

    def _tag_pfx(tag: str) -> str:
        m = re.match(r'^([A-Z]+)', (tag or '').upper())
        return m.group(1) if m else ''

    def _area_key(n: dict) -> str:
        return (n.get('area', '') or 'UNGROUPED').upper().strip()

    # ── Node partitions ────────────────────────────────────────────────────────
    equip_nodes = [n for n in nodes if n.get('pid_layer') == 1]
    instr_nodes = [n for n in nodes
                   if n.get('pid_layer') == 2
                   or n.get('category') == 'relief_valve'
                   or _canon(n) == 'relief']

    # Instrument lookup by loop number
    instr_by_num: dict[str, list] = defaultdict(list)
    instr_by_area: dict[str, list] = defaultdict(list)
    for n in instr_nodes:
        num = _tag_num(n.get('tag', ''))
        if num:
            instr_by_num[num].append(n)
        instr_by_area[_area_key(n)].append(n)

    # ── Group equipment by area ────────────────────────────────────────────────
    area_equip: dict[str, list] = defaultdict(list)
    for n in equip_nodes:
        area_equip[_area_key(n)].append(n)

    # ── Area type detection ────────────────────────────────────────────────────
    def _detect_type(area_name: str) -> str | None:
        low = area_name.lower()
        for atype, kws in _AREA_KW:
            if any(kw in low for kw in kws):
                return atype
        # Fallback: dominant equipment kind
        equip = area_equip.get(area_name, [])
        kinds = [_canon(n) for n in equip]
        for k in ('compressor', 'reactor', 'column', 'pump'):
            if k in kinds:
                return k
        return None

    def _tag_sort_num(tag: str) -> int:
        """Numeric sort key: extract first integer from a tag string."""
        m = re.search(r'(\d+)', tag or '')
        return int(m.group(1)) if m else 9999

    # ── Topological sort within area ───────────────────────────────────────────
    def _topo_sort(area_list: list) -> list:
        ids = {n['id'] for n in area_list}
        in_deg = {n['id']: 0 for n in area_list}
        loc_succ: dict[str, list] = {n['id']: [] for n in area_list}
        for f, ts in succ.items():
            if f in ids:
                for t in ts:
                    if t in ids:
                        loc_succ[f].append(t)
                        in_deg[t] += 1

        def _num(nid: str) -> int:
            tag = id_to_node.get(nid, {}).get('tag', '') or ''
            m = re.search(r'(\d+)', tag)
            return int(m.group(1)) if m else 9999

        # Sort initial roots by tag number so parallel paths come out numerically
        queue: list[str] = sorted([nid for nid in ids if in_deg[nid] == 0], key=_num)
        visited = set(queue)
        qi = 0
        while qi < len(queue):
            nid = queue[qi]; qi += 1
            ready = []
            for t in loc_succ.get(nid, []):
                in_deg[t] -= 1
                if in_deg[t] == 0 and t not in visited:
                    ready.append(t); visited.add(t)
            ready.sort(key=_num)   # numeric order among simultaneously-ready nodes
            queue.extend(ready)
        # Append cycle members / isolated nodes in tag-number order
        for n in sorted(area_list, key=lambda n: _num(n['id'])):
            if n['id'] not in visited:
                queue.append(n['id'])
        return [id_to_node[nid] for nid in queue if nid in id_to_node]

    # ── Pattern match score ────────────────────────────────────────────────────
    def _pat_score(sorted_nodes: list, ptype: str) -> float:
        pat = _PERRY_PATTERNS.get(ptype, [])
        if not pat:
            return 0.0
        matched, ni = 0, 0
        for slot in pat:
            kinds = _PAT_KINDS.get(slot, frozenset())
            while ni < len(sorted_nodes):
                if _canon(sorted_nodes[ni]) in kinds:
                    matched += 1; ni += 1; break
                ni += 1
        return matched / len(pat)

    # ── Instrument presence check ──────────────────────────────────────────────
    def _has_instr(equip: dict, req_pfx: str) -> bool:
        eid = equip['id']
        equip_num  = _tag_num(equip.get('tag', ''))
        equip_area = _area_key(equip)

        def _isa_ok(inst_tag: str) -> bool:
            p = _tag_pfx(inst_tag)
            # PSV / PRV — any relief tag satisfies
            if req_pfx.upper() in ('PSV', 'PRV', 'RV'):
                return p.startswith('PSV') or p.startswith('PRV') or p.startswith('RV') \
                       or p.startswith('SRV') or p.startswith('ORV')
            # Same first letter (measured variable) is sufficient
            return bool(p) and p[0].upper() == req_pfx[0].upper()

        # 1. Relief valve nodes near equipment
        if req_pfx.upper() in ('PSV', 'PRV', 'RV'):
            for n in nodes:
                if _canon(n) == 'relief' or n.get('category') == 'relief_valve':
                    if n['id'] in adj.get(eid, set()) or _area_key(n) == equip_area:
                        return True

        # 2. Same loop number
        if equip_num:
            for n in instr_by_num.get(equip_num, []):
                if _isa_ok(n.get('tag', '')):
                    return True

        # 3. Connected via signal edge
        for e in edges:
            if e.get('connType') != 'signal':
                continue
            oid = e['to'] if e['from'] == eid else (e['from'] if e['to'] == eid else None)
            if oid:
                other = id_to_node.get(oid)
                if other and _isa_ok(other.get('tag', '')):
                    return True

        # 4. Same area + matching loop number prefix (first 2 digits)
        if equip_num and len(equip_num) >= 2:
            loop_pfx2 = equip_num[:2]
            for n in instr_by_area.get(equip_area, []):
                inum = _tag_num(n.get('tag', ''))
                if inum and inum.startswith(loop_pfx2) and _isa_ok(n.get('tag', '')):
                    return True

        return False

    # ── Companion presence check ───────────────────────────────────────────────
    def _has_companion(equip: dict, comp_kind: str) -> bool:
        eid = equip['id']
        equip_area = _area_key(equip)
        kinds = _PAT_KINDS.get(comp_kind, frozenset({comp_kind}))
        for oid in adj.get(eid, set()):
            other = id_to_node.get(oid)
            if other and _canon(other) in kinds:
                return True
        for n in area_equip.get(equip_area, []):
            if n['id'] != eid and _canon(n) in kinds:
                return True
        return False

    # ── BUILD SEQUENCES ────────────────────────────────────────────────────────
    sequences: dict = {}
    for area_name, area_list in area_equip.items():
        if not area_list:
            continue
        atype = _detect_type(area_name)
        sorted_equip = _topo_sort(area_list)

        # Separation areas: Perry's §15 requires product cooler (HX) before separator
        # vessel regardless of edge topology — re-sort by kind priority then tag number
        if atype == 'separation':
            _sep_order = {'heat_exchanger': 0, 'filter': 2, 'pump': 3, 'vessel': 4}
            for _n in sorted_equip:
                _kc = _canon(_n)
                print(f'[sep sort] {_n.get("tag","?")} '
                      f'kind_canonical={_n.get("kind_canonical","—")} '
                      f'kind={_n.get("kind","—")} '
                      f'_canon={_kc} '
                      f'→ order={_sep_order.get(_kc, 5)}')
            sorted_equip = sorted(sorted_equip,
                                  key=lambda n: (_sep_order.get(_canon(n), 5),
                                                 _tag_sort_num(n.get('tag', ''))))

        # Compression areas: Perry's §10 pattern is suction drum → compressor → aftercooler → KO drum.
        # Kind-priority sort (vessel=0) groups ALL vessels together — wrong.
        # Instead: tag-sort first, then assign Perry positions by kind + order-within-kind:
        #   first vessel (lowest tag#) = suction drum → pos 0
        #   compressor(s)             → pos 1
        #   heat_exchanger(s)         → pos 2  (aftercooler)
        #   remaining vessels         → pos 3  (KO drum)
        if atype == 'compressor':
            _tag_sorted = sorted(sorted_equip, key=lambda n: _tag_sort_num(n.get('tag', '')))
            _first_vessel_tag = next(
                (n.get('tag', '') for n in _tag_sorted if _canon(n) == 'vessel'), None)
            def _comp_perry_pos(n: dict) -> tuple:
                k   = _canon(n)
                num = _tag_sort_num(n.get('tag', ''))
                if k == 'vessel' and n.get('tag', '') == _first_vessel_tag:
                    return (0, num)
                if k == 'compressor':
                    return (1, num)
                if k == 'heat_exchanger':
                    return (2, num)
                if k == 'vessel':
                    return (3, num)
                return (5, num)
            sorted_equip = sorted(sorted_equip, key=_comp_perry_pos)
            print(f'[verify compressor] {area_name}: '
                  f'{[n.get("tag", "?") + "(" + _canon(n) + ")" for n in sorted_equip]}')

        flow_order = [n.get('tag', n['id']) for n in sorted_equip]

        # Deduplicate dual-service HX pairs: HE-202A + HE-202B are the same physical
        # exchanger (A = cold/process side, B = hot/return side). Keep A, drop B.
        _a_bases = {re.sub(r'A$', '', t.upper())
                    for t in flow_order
                    if re.match(r'^(?:HE|HTX|X|QC)-\d+A$', t.upper())}
        flow_order = [t for t in flow_order
                      if not (re.match(r'^(?:HE|HTX|X|QC)-\d+B$', t.upper())
                              and re.sub(r'B$', '', t.upper()) in _a_bases)]
        score = _pat_score(sorted_equip, atype) if atype else 0.0
        confidence = 'high' if score >= 0.7 else 'medium' if score >= 0.4 else 'low'
        sequences[area_name] = {
            'pattern':    atype or 'unknown',
            'flow_order': flow_order,
            'confidence': confidence,
        }

    # ── BUILD COMPLETENESS ─────────────────────────────────────────────────────
    completeness: dict = {}
    for n in equip_nodes:
        tag  = n.get('tag', n['id'])
        kind = _canon(n)
        req  = _REQUIRED.get(kind)
        if not req:
            continue
        found:   list[str] = []
        missing: list[str] = []

        for comp_kind, desc in req.get('upstream', []):
            if _has_companion(n, comp_kind):
                found.append(f'{desc} ✓')
            else:
                missing.append(f'upstream {desc} ({comp_kind}) missing')

        for comp_kind, desc in req.get('downstream', []):
            if _has_companion(n, comp_kind):
                found.append(f'{desc} ✓')
            else:
                missing.append(f'downstream {desc} ({comp_kind}) missing')

        for comp_kind, desc in req.get('companions', []):
            if _has_companion(n, comp_kind):
                found.append(f'{desc} ✓')
            else:
                missing.append(f'{desc} ({comp_kind}) missing')

        for instr_req in req.get('instruments', []):
            pfx = instr_req.split('_')[0]   # 'LT_reflux' → 'LT', 'TT' → 'TT'
            if _has_instr(n, pfx):
                found.append(f'{instr_req} ✓')
            else:
                missing.append(f'{instr_req} not found')

        total = len(found) + len(missing)
        if total == 0:
            continue
        score_pct = round(len(found) / total * 20) * 5   # nearest 5%
        completeness[tag] = {
            'type':    kind,
            'found':   found,
            'missing': missing,
            'score':   f'{score_pct}%',
        }

    return {'sequences': sequences, 'completeness': completeness}


def _infer_area_rank(area_name: str) -> int:
    """Process-flow rank for area name (lower = earlier). 99 = unknown/utility."""
    a = area_name.upper()
    for i, kw in enumerate(_INFER_AREA_ORDER):
        if kw.upper() in a:
            return i
    return 99


def _node_area_rank(n: dict) -> int:
    """Area rank for a node: tag-digit override takes priority over area name."""
    tag = (n.get('tag') or n.get('label') or '').upper()
    dm = re.match(r'^[A-Z]+-(\d)', tag)
    if dm:
        r = _TAG_DIGIT_RANK.get(dm.group(1))
        if r is not None:
            return r
    return _infer_area_rank((n.get('area') or '').upper())


def infer_connections(nodes: list, edges: list, conventions=None) -> tuple[list, list]:
    """
    Post-extraction inference pass. Call after classify_node, before rendering.

    Five inference steps:
    1. Instrument-equipment association via ISA tag-number prefix matching
    2. Perry's equipment-companion inference (suction drums, interstage coolers)
    3. Dual-service HX A/B side annotation and process-edge re-routing
    4. Sequential process-pipe inference within areas (only when no edges exist)
    5. Cross-area process connection inference (only when no inter-area edge exists)

    Returns (nodes, inferred_edges).
      nodes          — same list objects; node dicts may gain equipment_ref /
                       dual_service_secondary / dual_service_primary fields.
      inferred_edges — new edge dicts, each carrying source='inferred'.
    """
    if not nodes:
        return nodes, []

    # ── Shared helpers ─────────────────────────────────────────────────────────
    def _canon(n: dict) -> str:
        return n.get('kind_canonical') or n.get('kind', '')

    def _tag_str(n: dict) -> str:
        return (n.get('tag') or n.get('label') or '').upper()

    def _tag_num_int(tag: str) -> int:
        m = re.search(r'(\d+)', tag or '')
        return int(m.group(1)) if m else 9999

    def _area_key(n: dict) -> str:
        return (n.get('area') or 'UNGROUPED').upper().strip()

    def _is_signal_e(e: dict) -> bool:
        return e.get('connType') == 'signal' or e.get('kind') == 'signal'

    def _is_process_e(e: dict) -> bool:
        ct = e.get('connType', 'process')
        return ct not in ('signal', 'inter_drawing') and e.get('kind', '') not in ('signal',)

    # ── Node partitions ────────────────────────────────────────────────────────
    equip_nodes = [n for n in nodes
                   if n.get('pid_layer') == 1 or _canon(n) in PROCESS_KINDS]
    instr_nodes = [n for n in nodes
                   if n.get('pid_layer') == 2 or _canon(n) in INSTRUMENT_KINDS]
    equip_id_set = {n['id'] for n in equip_nodes}
    instr_id_set = {n['id'] for n in instr_nodes}

    area_equip: dict[str, list] = defaultdict(list)
    for n in equip_nodes:
        area_equip[_area_key(n)].append(n)

    # ── Existing connectivity ──────────────────────────────────────────────────
    existing_pairs: set[tuple[str, str]] = set()   # undirected collision set
    instr_has_signal: set[str] = set()

    for e in edges:
        f, t = e.get('from', ''), e.get('to', '')
        if f and t:
            existing_pairs.add((f, t))
            existing_pairs.add((t, f))
        if _is_signal_e(e):
            if f in instr_id_set:
                instr_has_signal.add(f)
            if t in instr_id_set:
                instr_has_signal.add(t)

    inferred: list[dict] = []
    _ctr = [0]

    def _add(fid: str, tid: str, conn_type: str, label: str = '') -> bool:
        """Append inferred edge if not already present. Returns True if added."""
        if not fid or not tid or fid == tid:
            return False
        if (fid, tid) in existing_pairs:
            return False
        existing_pairs.add((fid, tid))
        existing_pairs.add((tid, fid))
        _ctr[0] += 1
        inferred.append({
            'id': f'inf_{_ctr[0]}',
            'from': fid, 'to': tid,
            'connType': conn_type,
            'source': 'inferred',
            'label': label,
        })
        return True

    # ── 1. Instrument-Equipment Association ────────────────────────────────────
    # ISA §4 convention: first 1-2 digits of loop number = equipment area.
    # FT-1012 → area prefix "10" → matches V-101, C-100, etc.
    _step1_new = _step1_skipped_ref = _step1_skipped_signal = _step1_no_match = 0
    for instr in instr_nodes:
        if instr['id'] in instr_has_signal:
            _step1_skipped_signal += 1
            continue
        if instr.get('equipment_ref'):
            _step1_skipped_ref += 1
            continue
        itag = _tag_str(instr)
        im = re.search(r'(\d+)', itag)
        if not im:
            _step1_no_match += 1
            continue
        inum = im.group(1)
        pfx2, pfx1 = inum[:2], inum[:1]

        # Prefer equipment in same area; fall back to all equipment
        candidates = area_equip.get(_area_key(instr)) or list(equip_nodes)

        best: dict | None = None
        best_score = -1
        best_dist  = 9999
        for equip in candidates:
            etag = _tag_str(equip)
            em = re.search(r'(\d+)', etag)
            if not em:
                continue
            es = em.group(1)
            if es[:2] == pfx2:
                score = 2
            elif es[:1] == pfx1:
                score = 1
            else:
                continue
            dist = abs(_tag_num_int(etag) - _tag_num_int(itag))
            if score > best_score or (score == best_score and dist < best_dist):
                best_score, best_dist, best = score, dist, equip

        if best:
            instr['equipment_ref'] = best.get('tag', best['id'])
            if _add(instr['id'], best['id'], 'signal'):
                instr_has_signal.add(instr['id'])
                _step1_new += 1
        else:
            _step1_no_match += 1

    print(f'[infer step1] new={_step1_new} skipped_ref={_step1_skipped_ref} '
          f'skipped_signal={_step1_skipped_signal} no_match={_step1_no_match} '
          f'total_instr={len(instr_nodes)}')

    # ── 2. Perry's Equipment-Companion Inference ───────────────────────────────
    # Infer compressor suction-drum and interstage-cooler connections that
    # extraction often misses. Uses tag-number-sorted area list as proxy
    # for flow order within each area.
    for area, eq_list in area_equip.items():
        sorted_eq = sorted(eq_list, key=lambda n: _tag_num_int(_tag_str(n)))
        kinds = [_canon(n) for n in sorted_eq]

        for idx, equip in enumerate(sorted_eq):
            k = kinds[idx]

            if k == 'compressor':
                # Suction drum: vessel immediately before compressor in tag-number order
                if idx > 0 and kinds[idx - 1] == 'vessel':
                    _add(sorted_eq[idx - 1]['id'], equip['id'], 'process', 'suction')
                # Aftercooler: HX immediately after compressor
                if idx + 1 < len(sorted_eq) and kinds[idx + 1] == 'heat_exchanger':
                    _add(equip['id'], sorted_eq[idx + 1]['id'], 'process', 'aftercooler')

            elif k == 'reactor':
                # Feed preheater: HX immediately before reactor
                if idx > 0 and kinds[idx - 1] == 'heat_exchanger':
                    _add(sorted_eq[idx - 1]['id'], equip['id'], 'process', 'feed')
                # Interstage cooler or second reactor immediately after
                if idx + 1 < len(sorted_eq) and kinds[idx + 1] in ('heat_exchanger', 'reactor'):
                    _add(equip['id'], sorted_eq[idx + 1]['id'], 'process')

    # ── 3. Dual-Service HX Annotation ─────────────────────────────────────────
    # HE-202A (cold/process side) and HE-202B (hot/return side) are the same
    # physical exchanger. Mark B as secondary; re-route B's extracted process
    # connections through A so topology is preserved.
    hx_sides: dict[str, dict] = {}
    for n in nodes:
        m = re.match(r'^((?:HE|HTX|X|QC)-\d+)([AB])$', _tag_str(n))
        if m:
            hx_sides.setdefault(m.group(1), {})[m.group(2)] = n

    for sides in hx_sides.values():
        if 'A' not in sides or 'B' not in sides:
            continue
        a_nd, b_nd = sides['A'], sides['B']
        b_nd['dual_service_secondary']  = True
        b_nd['dual_service_primary_id'] = a_nd['id']
        a_nd.setdefault('dual_service_primary', True)
        for e in edges:
            if _is_signal_e(e):
                continue
            f, t = e.get('from', ''), e.get('to', '')
            if f == b_nd['id'] and t != a_nd['id']:
                _add(a_nd['id'], t, 'process')
            elif t == b_nd['id'] and f != a_nd['id']:
                _add(f, a_nd['id'], 'process')

    # ── 4. Sequential Process-Pipe Inference ──────────────────────────────────
    # Within any area that has NO existing process edges at all, infer
    # connections between equipment whose tag numbers are adjacent (≤ 3 apart).
    # This fills in preheat trains and similar fully-disconnected areas.
    for area, eq_list in area_equip.items():
        if len(eq_list) < 2:
            continue
        area_ids = {n['id'] for n in eq_list}
        has_proc = any(
            _is_process_e(e)
            and e.get('from') in area_ids
            and e.get('to') in area_ids
            for e in edges
        )
        if has_proc:
            continue
        sorted_eq = sorted(eq_list, key=lambda n: _tag_num_int(_tag_str(n)))
        for i in range(len(sorted_eq) - 1):
            a, b = sorted_eq[i], sorted_eq[i + 1]
            if _tag_num_int(_tag_str(b)) - _tag_num_int(_tag_str(a)) <= 3:
                _add(a['id'], b['id'], 'process')

    # ── 5. Cross-Area Connection Inference ────────────────────────────────────
    # For consecutive process-flow areas (delivery→metering→compress→…),
    # connect the last equipment of area[N] to the first of area[N+1] only
    # when no process edge currently crosses that area boundary.
    ranked: dict[int, list] = defaultdict(list)
    _DEBUG_TAGS = {'V-5001', 'F-5001', 'F-5002'}
    for n in equip_nodes:
        r = _node_area_rank(n)
        tag = _tag_str(n)
        if tag in _DEBUG_TAGS:
            print(f'[infer step5] {tag} area="{_area_key(n)}" rank={r}')
        if r < 99:
            ranked[r].append(n)

    # Include inferred process edges in the cross-area connectivity check
    process_ep: set[tuple[str, str]] = set()
    for e in edges:
        if _is_process_e(e):
            f, t = e.get('from', ''), e.get('to', '')
            if f in equip_id_set and t in equip_id_set:
                process_ep.add((f, t))
    for e in inferred:
        if e['connType'] == 'process':
            process_ep.add((e['from'], e['to']))

    sorted_ranks = sorted(ranked.keys())
    for i, r1 in enumerate(sorted_ranks):
        nxt = [r for r in sorted_ranks if r > r1]
        if not nxt:
            continue
        r2 = nxt[0]
        if r2 - r1 > 2:
            continue   # areas not adjacent in standard process flow
        ids_r1 = {n['id'] for n in ranked[r1]}
        ids_r2 = {n['id'] for n in ranked[r2]}
        if any(f in ids_r1 and t in ids_r2 for f, t in process_ep):
            continue   # already connected across this boundary
        last_r1  = max(ranked[r1], key=lambda n: _tag_num_int(_tag_str(n)))
        first_r2 = min(ranked[r2], key=lambda n: _tag_num_int(_tag_str(n)))
        if _add(last_r1['id'], first_r2['id'], 'process'):
            process_ep.add((last_r1['id'], first_r2['id']))

    print(f'[infer_connections] {len(inferred)} inferred edges '
          f'(equip={len(equip_nodes)} instr={len(instr_nodes)} '
          f'signal={sum(1 for e in inferred if e["connType"]=="signal")} '
          f'process={sum(1 for e in inferred if e["connType"]=="process")})')
    return nodes, inferred
