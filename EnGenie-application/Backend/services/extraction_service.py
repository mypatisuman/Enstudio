"""
services/extraction_service.py — LLM extraction pipeline orchestration.

Extracted from main.py (Phase 7): the multi-pass Claude vision/text
extraction workflow — load_skills(), claude_extract_text(),
claude_extract_image() and its Pass 2/2.5 async helpers
(_batch_extract/_pipe_extract/_gather_passes), plus the small
extraction-result helpers file_hash(), _cache_key(), build_internal(),
extract_pdf_page() — all moved verbatim. This module coordinates the LLM
provider adapter, the CacheStore adapter, adapters.engine, and
utils.json_utils/domain.kind_mapping; it does not implement any CV/LLM
algorithm itself and contains no Flask/HTTP code.

`llm`, `cache_store`, and `studio_dir` are explicit parameters — these
functions originally closed over main.py's module-level `llm`, `cache_store`,
and `STUDIO_DIR` globals (the LLM provider and CacheStore are constructed
once at Flask app startup and passed in here rather than re-instantiated).
main.py keeps thin wrappers with the original signatures so every existing
call site is unchanged (see Phase 7 Step 5/6).

_extract_json_or_default() intentionally duplicates main.py's extract_json()
body (both call utils.json_utils.extract_json_object() and apply the same
empty-P&ID-shape default) rather than importing it from main.py — main.py
imports this service, so importing back from main.py would be a circular
import. The duplicated logic is 4 lines and reuses the same underlying
utils.json_utils engine, so there is no behavior drift risk.

Coordinates: utils.json_utils, domain.kind_mapping, adapters.engine
(lazy import, unchanged). No Flask, no request, no jsonify, no Blueprint.
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import io
from pathlib import Path

from utils.json_utils import extract_json_object
from domain.kind_mapping import CANONICAL_INSTR_KINDS, INSTRUMENT_KINDS


def _extract_json_or_default(raw: str) -> dict:
    """Mirrors main.py's extract_json() — see module docstring for why this
    isn't imported from main.py instead."""
    result = extract_json_object(raw)
    if result is not None:
        return result
    print(f'JSON extraction failed')
    return {'nodes': [], 'edges': [], 'instruments': {}, 'equipment': {}, 'connections': []}


# ── Skill loading ─────────────────────────────────────────────────────────────

_skills_cache: dict = {}  # 4c: load once, reuse across requests

def load_skills(drawing_type: str, studio_dir: Path) -> str:
    """Load all skill markdown files for a drawing type (cached at startup)."""
    if drawing_type in _skills_cache:
        return _skills_cache[drawing_type]
    skill_dir = studio_dir / 'skills' / 'core' / drawing_type
    user_dir = studio_dir / 'skills' / 'user'
    parts = []
    for d in [skill_dir, user_dir]:
        if d.exists():
            for f in sorted(d.glob('*.md')):
                if 'PLACEHOLDER' not in f.read_text()[:50]:
                    parts.append(f.read_text())
    result = '\n\n---\n\n'.join(parts)
    _skills_cache[drawing_type] = result
    return result


# ── Claude API calls ──────────────────────────────────────────────────────────

def claude_extract_text(text: str, llm, studio_dir: Path) -> dict:
    """Claude API for complex text that ympl.js Tier 1 could not handle."""
    skills = load_skills('p_and_id', studio_dir)
    prompt = f"""{skills}

Extract process topology from this description.
Return ONLY valid JSON — no markdown, no explanation:
{{
  "nodes": [{{"id": "n1", "label": "P-101", "kind": "pump"}}],
  "edges": [{{"from": "n1", "to": "n2", "kind": "stream", "label": "S-001"}}],
  "instruments": {{"FT-101": {{"type": "transmitter", "range_lo": 0, "range_hi": 500, "units": "kg/h", "equipment_ref": "E-101", "confidence": 0.9}}}},
  "equipment": {{"E-101": {{"area": "FEED", "description": ""}}}},
  "connections": [{{"from_tag": "E-101", "to_tag": "R-101", "fluid": "liquid", "line_size": "4in", "id": "S-001"}}]
}}

Input text: {text}"""
    try:
        resp = llm.complete(prompt, max_tokens=8000, tier='fast')
        return _extract_json_or_default(resp.text)
    except Exception as e:
        return {'error': str(e), 'nodes': [], 'edges': []}


def file_hash(data: bytes) -> str:
    """SHA256 hash of file bytes — cache key."""
    import hashlib
    return hashlib.sha256(data).hexdigest()[:16]


def _cache_key(fhash: str, pass_num: int) -> str:
    return f'{fhash}_pass{pass_num}'


# ── Parallel Pass 2 + 2.5 (async) ────────────────────────────────────────────

BATCH_SIZE = 30  # instruments per Haiku call

_PASS2_PROMPT = (
    'For these instrument tags on the P&ID: {tags}\n'
    'Extract parameters. Return ONLY JSON — no markdown:\n'
    '{{"FT-101": {{"type":"transmitter","equipment_ref":"E-101","range_lo":0.0,'
    '"range_hi":500.0,"units":"kg/h","alarm_hi":null,"alarm_hihi":null,'
    '"alarm_lo":null,"alarm_lolo":null,"fail_position":null,"confidence":0.92}}}}\n'
    'equipment_ref is REQUIRED — identify which equipment item (vessel, HX, reactor, pump, '
    'compressor) this instrument is physically mounted on or measuring. Use the equipment tag '
    'visible on the drawing (e.g. R-301, C-150). Only use null if the instrument is on a panel '
    'board (use panel tag e.g. PNL-100). Never return null for field-mounted instruments.\n'
    'Use null for other values not visible on the drawing. Only return tags from: {tags}'
)

_PASS25_PROMPT = (
    'Equipment tags on this P&ID: {proc_tags}\n\n'
    'For EVERY visible pipe run between equipment items, extract:\n'
    '- id: the full line designation if printed (e.g. 6"-PG-2001-A1B) or null\n'
    '- from_tag: upstream equipment tag\n'
    '- to_tag: downstream equipment tag\n'
    '- from_nozzle: nozzle label on from_tag if visible (inlet, outlet, N1…) or null\n'
    '- to_nozzle: nozzle label on to_tag if visible or null\n'
    '- fluid: process fluid (natural gas, crude, cooling water, steam…) or null\n'
    '- line_size: nominal pipe size (4", 6", DN100) or null\n'
    '- line_class: piping class (150#, 300#, A1B) or null\n'
    '- insulation: H, C, P, or null\n'
    '- to_drawing: destination drawing number if pipe exits page, else null\n\n'
    'Return ONLY JSON — no markdown:\n'
    '{{"connections": [{{"id": "6\\"-PG-2001-A1B", "from_tag": "E-101", "to_tag": "R-101",'
    ' "from_nozzle": "outlet", "to_nozzle": "N1", "fluid": "process gas",'
    ' "line_size": "6\\"", "line_class": "150#", "insulation": null, "to_drawing": null}}]}}'
)


async def _batch_extract(sem: asyncio.Semaphore,
                          image_b64: str, media_type: str,
                          batch: list, batch_num: int,
                          pid: str, fhash: str,
                          llm, cache_store,
                          conventions_text: str = '') -> dict:
    """Async instrument-parameter extraction for one batch of tags."""
    ck = f'{fhash}_b{batch_num}_pass2'
    cached = cache_store.get(pid, ck) if pid else None
    if cached:
        print(f'Pass 2 batch {batch_num}: cache hit ({len(cached)} tags)')
        return cached

    base = _PASS2_PROMPT.format(tags=', '.join(batch))
    prompt = (conventions_text + '\n\n' + base) if conventions_text else base
    t0 = datetime.datetime.now()
    async with sem:
        resp = await asyncio.to_thread(
            llm.complete_with_image, prompt, image_b64, media_type,
            max_tokens=8000, tier='fast',
        )
    elapsed = (datetime.datetime.now() - t0).total_seconds()
    result  = _extract_json_or_default(resp.text)
    n_got   = len(result) if isinstance(result, dict) else 0
    print(f'Pass 2 batch {batch_num}: {n_got}/{len(batch)} tags in {elapsed:.1f}s')
    if pid and isinstance(result, dict):
        cache_store.put(pid, ck, result, resp,
                        file_hash=fhash, pass_num=2)
    return result if isinstance(result, dict) else {}


async def _pipe_extract(sem: asyncio.Semaphore,
                         image_b64: str, media_type: str,
                         proc_tags: list, pid: str, fhash: str,
                         llm, cache_store,
                         conventions_text: str = '') -> dict:
    """Async pipe-run extraction (Pass 2.5)."""
    ck = f'{fhash}_pipes_pass3'
    cached = cache_store.get(pid, ck) if pid else None
    if cached:
        print(f'Pass 2.5: cache hit ({len(cached.get("connections", []))} pipe runs)')
        return cached
    if not proc_tags:
        return {'connections': []}

    base = _PASS25_PROMPT.format(proc_tags=', '.join(proc_tags))
    prompt = (conventions_text + '\n\n' + base) if conventions_text else base
    t0 = datetime.datetime.now()
    async with sem:
        resp = await asyncio.to_thread(
            llm.complete_with_image, prompt, image_b64, media_type,
            max_tokens=8000, tier='fast',
        )
    elapsed = (datetime.datetime.now() - t0).total_seconds()
    result  = _extract_json_or_default(resp.text)
    n_conn  = len(result.get('connections', [])) if isinstance(result, dict) else 0
    print(f'Pass 2.5: {n_conn} pipe runs in {elapsed:.1f}s')
    if pid and isinstance(result, dict) and result.get('connections'):
        cache_store.put(pid, ck, result, resp,
                        file_hash=fhash, pass_num=3)
        return result
    return {'connections': []}


async def _gather_passes(image_b64: str, media_type: str,
                          instr_tags: list, proc_tags: list,
                          pid: str, fhash: str,
                          llm, cache_store,
                          conventions_text: str = ''):
    """
    Orchestrate all Pass 2 instrument batches + Pass 2.5 pipe extraction
    in parallel with asyncio.gather().

    Semaphore(5) caps concurrent LLM calls; cache hits bypass it entirely.
    asyncio.to_thread() runs the synchronous provider methods in the thread
    pool so the event loop stays unblocked.
    Returns (batch_results_list, pipe_data_dict).
    """
    sem = asyncio.Semaphore(5)

    batch_tasks = [
        _batch_extract(sem, image_b64, media_type,
                       instr_tags[i:i + BATCH_SIZE],
                       i // BATCH_SIZE + 1, pid, fhash,
                       llm, cache_store,
                       conventions_text=conventions_text)
        for i in range(0, len(instr_tags), BATCH_SIZE)
    ]
    pipe_task = _pipe_extract(sem, image_b64, media_type, proc_tags, pid, fhash,
                               llm, cache_store,
                               conventions_text=conventions_text)

    results = await asyncio.gather(*batch_tasks, pipe_task, return_exceptions=True)
    return list(results[:-1]), results[-1]


def claude_extract_image(image_bytes: bytes, media_type: str = 'image/png',
                         pid: str = None, conventions_text: str = '',
                         *, llm, cache_store, studio_dir: Path) -> dict:
    """
    Multi-pass extraction with caching.
    Pass 1 (Sonnet, streaming): topology + positions.
    Pass 2 + 2.5 (Haiku, parallel async): instrument params + pipe runs.
    Same file hash = instant return from combined cache.
    """
    fhash = file_hash(image_bytes)
    print(f'File hash: {fhash}')

    # Combined cache hit — both passes done before for this file
    if pid:
        combined = cache_store.get(pid, _cache_key(fhash, 0))
        if combined:
            print('Full cache hit — skipping all API calls')
            return combined

    skills = load_skills('p_and_id', studio_dir)
    if conventions_text:
        skills = conventions_text + '\n\n---\n\n' + skills
    b64 = base64.standard_b64encode(image_bytes).decode()
    is_pdf = 'pdf' in media_type.lower()
    if not is_pdf and media_type not in ('image/png', 'image/jpeg', 'image/gif', 'image/webp'):
        media_type = 'image/png'

    # ── Pass 1: topology with area assignment (Option C) ─────────────────────
    topology = cache_store.get(pid, _cache_key(fhash, 1)) if pid else None
    if not topology:
        pass1_prompt = '''Extract ALL equipment and instrument tags from this P&ID set.
For EACH page/drawing, read the drawing number and title from the title block.
For EACH tag, estimate its position on its page as x,y from 0.0 to 1.0
where (0,0) = top-left corner of the drawing area, (1,1) = bottom-right.
Exclude the title block area from position estimation.

Return ONLY compact JSON — no markdown, no explanation:
{
  "drawings": [
    {"number": "157-2-130", "title": "REACTOR", "page": 8}
  ],
  "nodes": [
    {"id": "n1", "label": "E-101", "kind": "heat_exchanger", "drawing": "157-2-130", "area": "REACTOR", "x": 0.25, "y": 0.40},
    {"id": "n2", "label": "FT-101", "kind": "transmitter", "drawing": "157-2-130", "area": "REACTOR", "x": 0.30, "y": 0.55}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "kind": "stream", "label": "S-001"}
  ]
}
Kinds: vessel, separator, pump, valve, checkvalve, heat_exchanger, compressor,
column, reactor, absorber, relief, filter, meter,
transmitter, controller, indicator, recorder, switch, analyzer, element.
Be exhaustive. Include EVERY tag. Positions are approximate — engineer will adjust.
Main process flow runs left to right. Feed streams enter from left, products exit right.'''
        try:
            t1_start = datetime.datetime.now()
            p1_resp = llm.complete_streaming(
                pass1_prompt,
                system=skills,
                image_b64=b64,
                media_type=media_type,
                max_tokens=64000,
                tier='smart',
            )
            t1_elapsed = (datetime.datetime.now() - t1_start).total_seconds()
            topology = _extract_json_or_default(p1_resp.text)
            if pid and topology.get('nodes'):
                cache_store.put(pid, _cache_key(fhash, 1), topology, p1_resp,
                                file_hash=fhash, pass_num=1)
                n_areas = len({n.get('drawing','') for n in topology['nodes'] if n.get('drawing')})
                print(f'Pass 1: {len(topology["nodes"])} nodes, {n_areas} drawings, {t1_elapsed:.1f}s')
            elif not topology.get('nodes'):
                print('Pass 1 returned 0 nodes — NOT caching bad result')
        except Exception as e:
            return {'error': f'Pass 1 failed: {e}', 'nodes': [], 'edges': []}

    nodes = topology.get('nodes', [])
    edges = topology.get('edges', [])
    print(f'Pass 1: {len(nodes)} nodes, {len(edges)} edges')

    instr_tags = [n['label'] for n in nodes if n.get('kind') in CANONICAL_INSTR_KINDS]
    proc_tags  = [n['label'] for n in nodes if n.get('kind') not in CANONICAL_INSTR_KINDS]
    n_batches  = (len(instr_tags) + BATCH_SIZE - 1) // BATCH_SIZE if instr_tags else 0

    # ── Pass 2 + 2.5: parallel async extraction ───────────────────────────────
    print(f'Pass 2+2.5: {n_batches} batch(es) × {BATCH_SIZE} instruments + pipe extraction'
          f', concurrency ≤ 5')
    t_passes = datetime.datetime.now()

    try:
        batch_results, pipe_data = asyncio.run(
            _gather_passes(b64, media_type, instr_tags, proc_tags, pid, fhash,
                           llm, cache_store,
                           conventions_text=conventions_text)
        )
    except Exception as e:
        print(f'Parallel gather failed: {e}')
        batch_results = []
        pipe_data = {'connections': []}

    elapsed_passes = (datetime.datetime.now() - t_passes).total_seconds()
    print(f'Pass 2+2.5 wall time: {elapsed_passes:.1f}s')

    # Merge instrument results
    instruments = {}
    from adapters.engine import normalize_instrument_type
    for i, result in enumerate(batch_results):
        if isinstance(result, Exception):
            print(f'Pass 2 batch {i + 1} error: {result}')
            continue
        if isinstance(result, dict):
            for tag, data in result.items():
                if isinstance(data, dict) and 'type' in data:
                    data['type'] = normalize_instrument_type(data['type'])
            instruments.update(result)

    print(f'Pass 2: {len(instruments)} instruments enriched')

    equipment = {n['label']: {'area': n.get('area', ''), 'description': '',
                               'drawing': n.get('drawing', '')}
                 for n in nodes if n.get('kind') not in INSTRUMENT_KINDS}

    if isinstance(pipe_data, Exception):
        print(f'Pass 2.5 error: {pipe_data}')
        pipe_data = {'connections': []}
    connections = pipe_data.get('connections', [])
    print(f'Pass 2.5: {len(connections)} pipe runs')

    # Accumulate token / cost totals across all passes
    def _r_int(resp, attr): return int(getattr(resp, attr, 0) or 0)
    total_in  = _r_int(p1_resp, 'input_tokens')
    total_out = _r_int(p1_resp, 'output_tokens')
    total_cost = float(getattr(p1_resp, 'cost_usd', 0.0) or 0.0)
    result = {'nodes': nodes, 'edges': edges,
              'instruments': instruments, 'equipment': equipment,
              'connections': connections,
              '_tokens_in': total_in, '_tokens_out': total_out, '_cost_usd': total_cost,
              '_model': getattr(p1_resp, 'model', ''), '_provider': getattr(p1_resp, 'provider', '')}

    if pid:
        cache_store.put(pid, _cache_key(fhash, 0), result)  # combined cache

    return result


# ── Internal model builder ────────────────────────────────────────────────────

def build_internal(ympl_doc: dict, claude_data: dict) -> dict:
    """Merge YMPL topology with Claude enrichment into internal model."""
    from adapters.engine import ympl_to_internal
    return ympl_to_internal(ympl_doc, claude_data)


def extract_pdf_page(pdf_bytes: bytes, page_num: int) -> bytes:
    """Extract a single page (1-indexed) from a PDF as new PDF bytes."""
    from PyPDF2 import PdfReader, PdfWriter
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    page_idx = page_num - 1
    if 0 <= page_idx < len(reader.pages):
        writer.add_page(reader.pages[page_idx])
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
