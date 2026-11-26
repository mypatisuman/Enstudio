"""
helpers/editor_helper.py -- Pass-3/4-style tag/connectivity re-inference used
by the "arrange process" editor action.

Extracted from main.py (Phase 9): _editor_arrange_process_inner(), moved
verbatim. Already took `_re`/`_tb`/`_log` as explicit parameters before this
move (an existing convention in this function, unrelated to Phase 9); `llm`,
`skill_registry`, `infer_loops`, `load_espx`, and `_get_conventions` are
pulled in via a function-local `import main as _m` -- the same lazy-import
pattern used by the Phase 8 controllers -- since this function still needs
main.py's shared LLM provider / skill registry singletons and its
repository/service wrapper functions.
"""
from __future__ import annotations

import json

from flask_compat import jsonify


def _editor_arrange_process_inner(pid, _re, _tb, _log):
    import main as _m
    llm = _m.llm
    skill_registry = _m.skill_registry
    infer_loops = _m.infer_loops
    load_espx = _m.load_espx
    _get_conventions = _m._get_conventions
    espx, _ = load_espx(pid)
    if espx is None:
        return jsonify({'error': 'project not found'}), 404

    nodes_list = espx.get('nodes', [])
    if not nodes_list:
        return jsonify({'connections': [], 'process_sections': [], 'warnings': []})

    # ── Load skill + company conventions ─────────────────────────────────────
    skill = skill_registry.get_reconstruction_prompt() \
        or '(skill file not found - apply standard process engineering logic)'
    conv = _get_conventions(pid)
    if conv:
        skill = conv.as_skill_text() + '\n\n---\n\n' + skill

    # ── Drawing titles for process description context ────────────────────────
    drawings = espx.get('drawings', [])
    drawing_title_lines = [
        f"  {d.get('number', '?')}: {d.get('title', '')}"
        for d in drawings if d.get('title')
    ]
    process_description = '\n'.join(drawing_title_lines) if drawing_title_lines else \
        '  (no drawing titles available)'

    # ── Area name lookup: digit key → set of full area descriptions ───────────
    area_names: dict = {}
    for _n in nodes_list:
        _lbl = _n.get('label', _n['id'])
        _akey = _lbl[_re.search(r'\d', _lbl).start()] if _re.search(r'\d', _lbl) else '0'
        _aname = (_n.get('area', '') or '').strip().upper()
        if _aname:
            area_names.setdefault(_akey, set()).add(_aname)

    def _area_pattern(area_key):
        """Return (pattern_type, sequence_hint) for a 1-digit area key."""
        desc = ' '.join(area_names.get(area_key, set())).lower()
        if any(w in desc for w in ('compress', 'compressor')):
            return 'compression', 'suction drum → compressor → aftercooler → KO drum'
        if 'preheat' in desc or 'preheater' in desc:
            return 'preheat', 'cold feed → HX-1 → HX-2 → HX-3 → reactor feed'
        if 'react' in desc:
            return 'reactor', 'preheated feed → reactor → interstage cooler → next reactor'
        if 'separ' in desc or 'product' in desc:
            return 'separation', \
                'product cooler → HP separator → flash drums → filters → pumps → collection'
        if 'feed' in desc or 'storage' in desc or 'inlet' in desc:
            return 'feed', 'storage tank → vaporizer/HX → pressure regulator → metering'
        if _re.search(r'glycol|hot.?oil|lube.?oil|instrument.?air|plant.?air|vent|electrical',
                      desc):
            return 'utility', 'closed loop: supply header → process users → return header'
        return 'general', 'connect equipment in tag-number order'

    # ── Tag lookups ───────────────────────────────────────────────────────────
    def _nt(t): return _re.sub(r'[^A-Z0-9]', '', t.upper()) if t else ''
    tag_to_id: dict = {}
    norm_to_id: dict = {}
    id_to_node: dict = {}
    for n in nodes_list:
        lbl = n.get('label', n['id'])
        tag_to_id[lbl] = n['id']
        nk = _nt(lbl)
        if nk and nk not in norm_to_id:
            norm_to_id[nk] = n['id']
        id_to_node[n['id']] = n

    def _resolve(tag):
        if not tag: return ''
        return tag_to_id.get(tag) or norm_to_id.get(_nt(tag), '')

    def _area_of(tag):
        """First digit of the numeric portion of a tag — encodes process area."""
        m = _re.search(r'\d', tag)
        return m.group() if m else '0'

    # ── Collect already-connected process pairs ───────────────────────────────
    process_adj: set = set()
    connected_pairs: list = []

    def _record(fid, tid):
        fn = id_to_node.get(fid, {})
        tn = id_to_node.get(tid, {})
        ft = fn.get('label', fid)
        tt = tn.get('label', tid)
        if ft and tt:
            connected_pairs.append((ft, tt))
        process_adj.add(fid)
        process_adj.add(tid)

    for e in espx.get('edges', []):
        if e.get('kind', '') != 'signal':
            _record(e.get('from', ''), e.get('to', ''))
    for e in espx.get('editor_state', {}).get('edges', []):
        if e.get('connType', '') != 'signal':
            _record(e.get('from', ''), e.get('to', ''))
    for c in espx.get('studio', {}).get('connections', []):
        fid = _resolve(c.get('from_tag', ''))
        tid = _resolve(c.get('to_tag', ''))
        if fid and tid:
            _record(fid, tid)

    # ── Identify dangling nodes ───────────────────────────────────────────────
    _ALL_VALVE_PFX = ('FCV', 'LCV', 'PCV', 'TCV', 'HCV', 'XV', 'SDV', 'BDV',
                      'PSV', 'PRV', 'SV', 'FV', 'LV', 'TV', 'PV')
    _VALVE_GROUPS_KEYS = ('FCV', 'PCV', 'TCV', 'LCV', 'XV', 'PSV', 'PRV', 'OTHER')
    EQUIP_KINDS = {'vessel', 'separator', 'pump', 'heat_exchanger', 'compressor',
                   'column', 'reactor', 'absorber', 'filter'}

    # area -> list of dangling items
    area_equip: dict  = {}   # area -> [{'tag','kind','drawing'}]
    area_valves: dict = {}   # area -> [{'tag','drawing','group'}]

    for n in nodes_list:
        nid = n['id']
        if nid in process_adj:
            continue
        kind  = n.get('kind', '')
        label = n.get('label', n['id'])
        dwg   = n.get('drawing', '')
        lu    = label.upper()
        a     = _area_of(label)

        if kind in EQUIP_KINDS:
            area_equip.setdefault(a, []).append({'tag': label, 'kind': kind, 'drawing': dwg})
        elif kind == 'valve' or any(lu.startswith(p) for p in _ALL_VALVE_PFX):
            grp = next((k for k in _VALVE_GROUPS_KEYS if lu.startswith(k)), 'OTHER')
            area_valves.setdefault(a, []).append({'tag': label, 'drawing': dwg, 'group': grp})

    total_dangling_equip  = sum(len(v) for v in area_equip.values())
    total_dangling_valves = sum(len(v) for v in area_valves.values())

    if not total_dangling_equip and not total_dangling_valves:
        return jsonify({'connections': [], 'process_sections': [], 'warnings': [],
                        'message': 'No dangling nodes found'})

    _log(f'[arrange-process] pid={pid}  dangling_equip={total_dangling_equip}'
         f'  dangling_valves={total_dangling_valves}'
         f'  connected_pairs={len(connected_pairs)}')

    # ── Per-area context: connected pairs, loops, instr refs ──────────────────
    loops = infer_loops(espx)

    area_conn_ctx: dict  = {}   # area -> [(ft, tt)]
    for ft, tt in connected_pairs:
        for a in {_area_of(ft), _area_of(tt)}:
            area_conn_ctx.setdefault(a, []).append((ft, tt))

    area_loop_ctx: dict  = {}   # area -> [line]
    for lid, ld in loops.items():
        # lid is a tuple ('F', '101'); second element is loop number
        num = str(lid[1]) if isinstance(lid, tuple) and len(lid) > 1 else str(lid)
        a   = num[0] if num else '0'
        parts = []
        if ld.get('controller'):    parts.append(f"ctrl={ld['controller']}")
        if ld.get('measurement'):   parts.append(f"meas={ld['measurement']}")
        if ld.get('final_element'): parts.append(f"valve={ld['final_element']}")
        if parts:
            area_loop_ctx.setdefault(a, []).append(f"  {num}: {', '.join(parts)}")

    area_iref_ctx: dict  = {}   # area -> [line]
    for tag, data in espx.get('studio', {}).get('instruments', {}).items():
        if not isinstance(data, dict): continue
        ref = (data.get('equipment_ref') or '').strip()
        if not ref: continue
        a = _area_of(tag)
        area_iref_ctx.setdefault(a, []).append(f"  {tag} -> {ref}")

    # ── LLM caller with partial-recovery JSON parsing ────────────────────────
    def _call_haiku(prompt_text, label='call', out_sections=None):
        try:
            resp = llm.complete(prompt_text, max_tokens=4096, tier='fast')
            raw  = resp.text
        except Exception as e:
            _log(f'[arrange-process]   {label} LLM API error: {e}')
            return []

        # Try array first, then wrapped object
        json_str = raw
        fence = _re.search(r'```(?:json)?\s*([\s\S]*?)```', raw)
        if fence:
            json_str = fence.group(1).strip()
        else:
            s = raw.find('['); end = raw.rfind(']')
            if s != -1 and end != -1:
                json_str = raw[s:end + 1]
            else:
                s = raw.find('{'); end = raw.rfind('}')
                if s != -1 and end != -1:
                    json_str = raw[s:end + 1]
        try:
            parsed = json.loads(json_str)
            if isinstance(parsed, list):
                return parsed
            if isinstance(parsed, dict):
                if out_sections is not None:
                    out_sections.extend(parsed.get('process_sections', []))
                return parsed.get('connections', [])
        except Exception:
            pass

        # Partial recovery — extract every complete connection object
        partial = []
        for m in _re.finditer(
                r'\{[^{}]*"from_tag"\s*:\s*"[^"]+"\s*,[^{}]*"to_tag"\s*:\s*"[^"]+"\s*[^{}]*\}',
                raw):
            try:
                partial.append(json.loads(m.group()))
            except Exception:
                pass
        if partial:
            _log(f'[arrange-process]   {label} partial recovery: {len(partial)} objects')
        return partial

    # ── Per-area Claude calls ─────────────────────────────────────────────────
    NL = '\n'
    all_raw_conns: list = []
    all_sections:  list = []
    areas = sorted(set(list(area_equip.keys()) + list(area_valves.keys())))

    for area in areas:
        eq = area_equip.get(area, [])
        vv = area_valves.get(area, [])
        if not eq and not vv:
            continue

        conn_ctx  = area_conn_ctx.get(area, [])[:50]
        loop_ctx  = area_loop_ctx.get(area,  [])[:50]
        iref_ctx  = area_iref_ctx.get(area,  [])[:50]

        conn_block  = NL.join(f"  {ft} -> {tt}" for ft, tt in conn_ctx) or '  (none)'
        equip_block = NL.join(
            f"  {d['tag']} ({d['kind']}) dwg={d['drawing'] or '?'}" for d in eq
        ) or '  (none)'

        vgrps: dict = {}
        for v in vv:
            vgrps.setdefault(v['group'], []).append(v['tag'])
        valve_block = NL.join(
            f"  {g}: " + ', '.join(tags) for g, tags in vgrps.items()
        ) or '  (none)'

        loop_block = NL.join(loop_ctx)  or '  (none)'
        iref_block = NL.join(iref_ctx)  or '  (none)'

        pattern_type, pattern_hint = _area_pattern(area)
        area_label_set = area_names.get(area, set())
        area_label = ', '.join(sorted(area_label_set)) or f'Area {area}'

        prompt = (
            skill + "\n\n"
            "═══════════════════════════════════════════════════════\n"
            f"PROCESS DESCRIPTION (from drawing titles):\n{process_description}\n\n"
            f"THIS AREA: {area_label} (digit {area})"
            f" — PATTERN: {pattern_type.upper()}\n"
            f"Expected sequence: {pattern_hint}\n\n"
            "STANDARD PROCESS PATTERNS:\n"
            "- Feed storage: storage tank → vaporizer/HX → pressure regulator → metering\n"
            "- Compression: suction drum → compressor → aftercooler → KO drum\n"
            "- Preheat train: cold feed → HX series (A/B suffix = parallel units) → reactor\n"
            "- Reactor: preheated feed → reactor → interstage cooler → next reactor\n"
            "- Separation: product cooler → HP separator → flash drums"
            " → filters → pumps → collection\n"
            "- Utility: closed loop supply → process users → return\n\n"
            f"AREA {area} ALREADY CONNECTED (do not duplicate):\n"
            + conn_block + "\n\n"
            f"AREA {area} DANGLING EQUIPMENT:\n" + equip_block + "\n\n"
            f"AREA {area} DANGLING VALVES:\n" + valve_block + "\n\n"
            f"AREA {area} CONTROL LOOPS:\n" + loop_block + "\n\n"
            f"AREA {area} INSTRUMENT-EQUIPMENT REFERENCES:\n" + iref_block + "\n\n"
            "ENGINEERING RULES (apply all 10):\n"
            "1. Apply the standard pattern for this area type\n"
            "2. Within an area, connect equipment in tag-number order"
            " unless the pattern dictates otherwise\n"
            "3. Pumps ALWAYS follow vessels: V-xxx → P-xxx\n"
            "4. HXs with A/B suffix are PARALLEL — connect both to same"
            " upstream and downstream\n"
            "5. Compressor section: suction drum → compressor → aftercooler → KO drum\n"
            "6. Reactor section: preheat → reactor → cooler → next reactor\n"
            "7. Separator section: cooler → HP sep → flash → filter → pump → collection\n"
            "8. Utility areas: closed loops, separate from main process\n"
            "9. Recycle: if compressor suction connects to separator gas outlet,"
            " show the recycle loop\n"
            "10. Cross-area connections: preheat feeds reactor, reactor feeds separator\n\n"
            "Return a JSON object with BOTH arrays:\n"
            '{\n'
            '  "connections": [{"from_tag":"V-101","to_tag":"P-101",'
            '"kind":"stream","reasoning":"..."}],\n'
            '  "process_sections": [{"area":"' + area_label + '",'
            '"pattern":"' + pattern_type + '",'
            '"flow_order":["V-101","P-101"],"description":"..."}]\n'
            '}'
        )

        _log(f'[arrange-process] Area {area} ({area_label}): {len(eq)} equip + {len(vv)} valves'
             f'  pattern={pattern_type}  conn_ctx={len(conn_ctx)} -> calling Haiku...')
        raw_conns = _call_haiku(prompt, label=f'area-{area}', out_sections=all_sections)
        _log(f'[arrange-process] Area {area}: {len(raw_conns)} connections returned')
        all_raw_conns.extend(raw_conns)

    # ── Post-process: motors always get signal edges ──────────────────────────
    for c in all_raw_conns:
        if (c.get('from_tag', '').upper().startswith('M-') or
                c.get('to_tag', '').upper().startswith('M-')):
            c['kind'] = 'signal'

    # ── Resolve all raw connections → node IDs, dedup ────────────────────────
    existing_pairs: set = set()
    for e in espx.get('edges', []):
        existing_pairs.add(f"{e['from']}|{e['to']}")
        existing_pairs.add(f"{e['to']}|{e['from']}")
    for e in espx.get('editor_state', {}).get('edges', []):
        existing_pairs.add(f"{e['from']}|{e['to']}")
        existing_pairs.add(f"{e['to']}|{e['from']}")

    conn_type_map = {'stream': 'process', 'signal': 'signal'}
    resolved: list = []
    skipped_unresolved = skipped_duplicate = 0

    for c in all_raw_conns:
        ft  = c.get('from_tag', '')
        tt  = c.get('to_tag', '')
        fid = _resolve(ft)
        tid = _resolve(tt)
        if not fid or not tid or fid == tid:
            skipped_unresolved += 1
            continue
        pair = f'{fid}|{tid}'
        if pair in existing_pairs:
            skipped_duplicate += 1
            continue
        existing_pairs.add(pair)
        existing_pairs.add(f'{tid}|{fid}')
        resolved.append({
            'from': fid, 'to': tid,
            'connType': conn_type_map.get(c.get('kind', 'stream'), 'process'),
            'from_tag': ft, 'to_tag': tt,
            'reasoning': c.get('reasoning', ''),
        })

    _log(f'[arrange-process] Total resolved={len(resolved)}'
         f'  skip_unresolved={skipped_unresolved}'
         f'  skip_dup={skipped_duplicate}')

    # ── Post-process: targeted fix-up for half-connected valves ──────────────
    # Build per-valve connection lists from resolved (process edges only)
    valve_conns: dict = {}   # tag -> [(from_tag, to_tag)]
    for c in resolved:
        if c['connType'] != 'process':
            continue
        for tag in (c['from_tag'], c['to_tag']):
            if any(tag.upper().startswith(p) for p in _ALL_VALVE_PFX):
                valve_conns.setdefault(tag, []).append((c['from_tag'], c['to_tag']))

    half_valves = [(tag, conns) for tag, conns in valve_conns.items()
                   if len(conns) == 1]

    if half_valves:
        _log(f'[arrange-process] Valve fix-up: {len(half_valves)} valves need a 2nd connection')
        # Process in batches of 30
        for batch_start in range(0, len(half_valves), 30):
            batch = half_valves[batch_start:batch_start + 30]
            valve_info_lines = []
            for vtag, conns in batch:
                ft, tt = conns[0]
                if ft == vtag:
                    side = f"already has upstream=? and downstream={tt} — need upstream"
                else:
                    side = f"already has upstream={ft} and downstream=? — need downstream"
                a = _area_of(vtag)
                # Candidate equipment in same area for context
                cands = [n.get('label', n['id']) for n in nodes_list
                         if _area_of(n.get('label', n['id'])) == a
                         and n.get('label', n['id']) != vtag
                         and n.get('kind', '') in EQUIP_KINDS][:12]
                valve_info_lines.append(
                    f"  {vtag}: {side} | area-{a} equipment: {', '.join(cands)}")

            fixup_prompt = (
                skill + "\n\n"
                "VALVE FIX-UP: Each valve below has exactly ONE process connection.\n"
                "Every control valve must sit BETWEEN two equipment items.\n"
                "Identify only the MISSING second connection for each valve.\n\n"
                "VALVES NEEDING A SECOND CONNECTION:\n"
                + NL.join(valve_info_lines) + "\n\n"
                "Return ONLY a JSON array:\n"
                '[{"from_tag":"E-101","to_tag":"FCV-1019","kind":"stream","reasoning":"..."}]'
            )

            _log(f'[arrange-process] Valve fix-up batch {batch_start//30 + 1}'
                 f' ({len(batch)} valves) -> calling Haiku...')
            fixup_conns = _call_haiku(fixup_prompt, label='valve-fixup')
            _log(f'[arrange-process] Valve fix-up: {len(fixup_conns)} connections returned')

            for c in fixup_conns:
                if (c.get('from_tag', '').upper().startswith('M-') or
                        c.get('to_tag', '').upper().startswith('M-')):
                    c['kind'] = 'signal'
                ft  = c.get('from_tag', '')
                tt  = c.get('to_tag', '')
                fid = _resolve(ft)
                tid = _resolve(tt)
                if not fid or not tid or fid == tid:
                    continue
                pair = f'{fid}|{tid}'
                if pair in existing_pairs:
                    continue
                existing_pairs.add(pair)
                existing_pairs.add(f'{tid}|{fid}')
                resolved.append({
                    'from': fid, 'to': tid,
                    'connType': conn_type_map.get(c.get('kind', 'stream'), 'process'),
                    'from_tag': ft, 'to_tag': tt,
                    'reasoning': '[valve fix-up] ' + c.get('reasoning', ''),
                })

    # ── Validation pass ───────────────────────────────────────────────────────
    warnings: list = []

    proc_degree: dict = {}
    for c in resolved:
        if c['connType'] == 'process':
            proc_degree[c['from_tag']] = proc_degree.get(c['from_tag'], 0) + 1
            proc_degree[c['to_tag']]   = proc_degree.get(c['to_tag'],   0) + 1

    valve_degree: dict = {}
    for c in resolved:
        if c['connType'] != 'process':
            continue
        for tag in (c['from_tag'], c['to_tag']):
            if any(tag.upper().startswith(p) for p in _ALL_VALVE_PFX):
                valve_degree[tag] = valve_degree.get(tag, 0) + 1

    for tag, deg in valve_degree.items():
        if deg != 2:
            warnings.append(f"Valve {tag} has {deg} process connection(s) - expected 2")

    for tag, deg in proc_degree.items():
        if deg > 4 and not tag.upper().startswith('M-'):
            warnings.append(f"Equipment {tag} has {deg} process connections - may be too many")

    if warnings:
        _log(f'[arrange-process] {len(warnings)} validation warning(s):')
        for w in warnings[:10]:
            _log(f'[arrange-process]   WARNING: {w}')
        if len(warnings) > 10:
            _log(f'[arrange-process]   ... and {len(warnings) - 10} more')
    else:
        _log('[arrange-process] validation OK - no warnings')

    _log(f'[arrange-process] DONE - returning {len(resolved)} edges, '
         f'{len(warnings)} warnings')

    return jsonify({
        'connections':      resolved,
        'process_sections': all_sections,
        'warnings':         warnings,
        'counts':           {'arranged': len(resolved)},
    })
