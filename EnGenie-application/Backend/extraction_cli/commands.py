"""
extraction_cli/commands.py -- extraction workflow orchestration: the full
CV + LLM verification pipeline (run_extraction), plus result-merge and
run-finalization helpers.

Extracted from extract_cli.py (Phase 11), moved verbatim. run_extraction's
`import main as _s` stays a function-local lazy import exactly as before
(main.py reads ENGINEERING_HUB at module level, which this function sets
just before importing it).
"""
from __future__ import annotations

import asyncio
import base64
import datetime
import json
import math
import os
import re
import sys
from pathlib import Path

from connectivity_graph import build_geometric_connectivity

from .output import emit, die
from .pdf import _render_pdf_to_png, _pdf_page_count
from .image import (
    _run_full_cv,
    _filter_degenerate_segments, _segs_to_dicts, _snap_segments_to_symbols,
)
from .llm_verification import (
    _build_symbol_summary, _build_connection_summary, _call_llm_verification,
    _chain_pixel_segments, _format_proposed_graph, _call_llm_connections,
    LlmStageError,
)
from .status import ExtractionStatus, Reason



def _is_llm_junction(jid) -> bool:
    """True for a junction id LLM B invented, rather than one geometry built.

    Structural, not textual. build_geometric_connectivity names every junction
    it creates "gj_<integer>" and nothing else, so anything that does not match
    that shape came from the model.

    The first version of this test matched the "gj_new" prefix, because the
    connections prompt says 'assign it a fresh id like gj_new_1'. That is an
    EXAMPLE, not a rule, and the model does not follow it: a real run produced
    gj_tap_n39, gj_train1_C, gj_cwr_2, gj_n47_c1 — 13 invented junctions, none
    with that prefix, so every one of them slipped past both the grounding and
    the pruning and left a dead dot on the canvas.
    """
    return bool(jid) and not re.fullmatch(r'gj_\d+', str(jid))

def _page_prefix(page_no: int, total_pages: int) -> str:
    """Page component of the id namespace.

    Empty for a single-page document, so a 1-page extraction produces exactly
    the ids it always did ("n1", "gj_0") and existing projects, caches and
    tests are unaffected. Multi-page documents get "p{N}_" so page 2's "n1"
    cannot overwrite page 1's "n1" — the nodes table is keyed (id, pid), so
    without this the second page silently REPLACEs the first page's rows.
    """
    return '' if total_pages <= 1 else f'p{page_no}_'


def _fallback_drawing(source_id: int | None, page_no: int, total_pages: int) -> str:
    """Drawing label for a page whose title block gave us no drawing number.

    Must be unique per (document, page): the canvas groups symbols into sheet
    cells by this string, so a label shared by two documents merges their
    drawings into one cell. Empty when there is no document identity and only
    one page — the historic single-page value, kept so existing projects and
    tests are unaffected.
    """
    if source_id is None:
        return f'page_{page_no}' if total_pages > 1 else ''
    return f'doc{int(source_id)}' if total_pages <= 1 else f'doc{int(source_id)}_p{page_no}'


def _id_prefix(source_id: int | None, page_no: int, total_pages: int) -> str:
    """Full id namespace for one page of one document: "s{src}_p{page}_".

    Phase 5. _page_prefix alone made ids unique WITHIN a document, which left
    the cross-document case open: two PDFs in the same project both produce
    "n1" on their page 1, and the nodes table is keyed (id, pid), so whichever
    extraction ran second replaced the first document's rows.

    The document component is `sources.id` — the identity the application
    already assigns on upload (commands/ingest.rs) and already passes to
    run_extraction. No second identity system is introduced.

    Omitted entirely when source_id is None so the Flask path, tests, and any
    caller without a sources row keep producing the ids they always did.
    """
    src = '' if source_id is None else f's{int(source_id)}_'
    return f'{src}{_page_prefix(page_no, total_pages)}'


def _scope_ids(prefix: str, nodes: list, edges: list) -> None:
    """Rewrite node ids and edge endpoints in place with `prefix`.

    Applied after a page is fully extracted, so everything upstream (YOLO
    "n{i+1}" indexing, geometry junction "gj_N" ids, the LLM's own
    cross-references) keeps working on the plain per-page ids it expects.
    """
    if not prefix:
        return
    for n in nodes:
        if n.get('id'):
            n['id'] = f"{prefix}{n['id']}"
        if n.get('equipment_ref'):
            n['equipment_ref'] = f"{prefix}{n['equipment_ref']}"
        if n.get('merged_from'):
            n['merged_from'] = [f'{prefix}{m}' for m in n['merged_from']]
    for e in edges:
        if e.get('from'):
            e['from'] = f"{prefix}{e['from']}"
        if e.get('to'):
            e['to'] = f"{prefix}{e['to']}"


def run_extraction(hub: Path, pid: str, source_path: Path,
                   llm_only: bool = False, source_id: int | None = None) -> None:
    """
    Full CV + LLM verification pipeline over EVERY page of the source.

    Phase 1: this used to render `doc[0]` only and then REPLACE the project
    with that one page's result, so a 20-sheet drawing set produced one sheet
    and reported success. It now iterates pages, keeps each page's
    coordinates in that page's own normalised space, namespaces ids per page,
    and merges once at the end.

    Emits NDJSON progress lines. Pass llm_only=True to skip CV re-detection
    and reuse cached JSON files.
    """

    # Bootstrap: set env var before importing main (reads it at module level)
    os.environ['ENGINEERING_HUB'] = str(hub)

    if sys.platform == 'win32' and sys.version_info < (3, 12):
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    # commands.py now lives one directory deeper (extraction_cli/commands.py)
    # than the original extract_cli.py, so this needs an extra .parent to
    # still resolve to <studio>/ (where main.py, the Flask app, lives).
    studio_dir = Path(__file__).parent.parent
    if str(studio_dir) not in sys.path:
        sys.path.insert(0, str(studio_dir))

    try:
        import main as _s
    except Exception as e:
        die(f"Cannot import studio: {e}")

    emit({"stage": "init", "status": "ok",
          "hub": str(hub), "pid": pid, "file": source_path.name,
          "db": str(hub / 'studio.db')})

    # ── Read source file ───────────────────────────────────────────────────────
    try:
        raw_bytes = source_path.read_bytes()
    except OSError as e:
        die(f"Cannot read file: {e}")

    suffix = source_path.suffix.lower()
    is_pdf = suffix == '.pdf'

    if is_pdf:
        total_pages = _pdf_page_count(raw_bytes)
        if total_pages < 1:
            die("PDF has no pages, or could not be opened")
    else:
        total_pages = 1

    fhash     = _s.file_hash(raw_bytes)
    safe_name = re.sub(r'[^\w\-_. ]', '_', source_path.name).strip() or 'source.pdf'

    emit({"stage": "hash", "status": "ok",
          "hash": fhash, "bytes": len(raw_bytes), "filename": safe_name,
          "pages": total_pages})

    # ── Ensure project directories and DB row exist ────────────────────────────
    proj_dir  = _s.PROJECTS_DIR / pid
    cache_dir = str(proj_dir / 'cache')
    (proj_dir / 'source_docs').mkdir(parents=True, exist_ok=True)
    (proj_dir / 'cache').mkdir(parents=True, exist_ok=True)
    (proj_dir / 'source_docs' / safe_name).write_bytes(raw_bytes)

    from adapters import db as _db
    _db.get_db().execute(
        'INSERT OR IGNORE INTO projects (id, title, status) VALUES (?, ?, ?)',
        (pid, pid, 'pending')
    )

    # ── Cache check (combined pass-0 key) ─────────────────────────────────────
    ck0 = _s._cache_key(fhash, 0)

    from adapters.config import load_config
    _cfg = load_config()
    provider = _cfg.get('llm_provider', 'anthropic').lower()

    # ── Check API key before calling LLM (set from the frontend Settings
    # screen and read from the database — no env var fallback) ───────────────
    if provider == 'anthropic' and not _cfg.get('anthropic_api_key'):
        die("Anthropic API key not set — configure it in Settings")
    elif provider == 'gemini' and not _cfg.get('gemini_api_key'):
        die("Gemini API key not set — configure it in Settings")
    elif provider == 'openai' and not _cfg.get('openai_api_key'):
        die("OpenAI API key not set — configure it in Settings")
    elif provider.startswith('custom:') and not _cfg.get(f'custom_{provider[len("custom:"):]}_api_key'):
        die(f"{provider} API key not set — configure it in Settings")

    # ── Per-page extraction ───────────────────────────────────────────────────
    all_nodes: list = []
    all_edges: list = []
    all_loops: list = []
    all_geometry: list = []
    page_reports: list = []
    cv_totals = {'symbol_count': 0, 'text_count': 0, 'line_count': 0}
    usage_total = {'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0,
                   'model': '', 'provider': ''}

    for page_no in range(1, total_pages + 1):
        emit({"stage": "page", "status": "running",
              "page": page_no, "of": total_pages})

        if is_pdf:
            try:
                page_bytes, page_w, page_h = _render_pdf_to_png(raw_bytes, page_no - 1)
            except SystemExit:
                raise
            except Exception as e:
                die(f"PDF render failed on page {page_no}: {e}")
        else:
            page_bytes, page_w, page_h = raw_bytes, 0, 0

        # Cache file basename. Single-page keeps the historic "{pid}_*.json"
        # names so --llm-only still finds caches written before Phase 1.
        base_name = pid if total_pages <= 1 else f'{pid}_p{page_no}'

        try:
            page_result = _extract_one_page(
                _s, page_bytes, page_w, page_h, page_no, total_pages,
                base_name, cache_dir, provider, llm_only,
            )
        except SystemExit:
            raise

        prefix = _id_prefix(source_id, page_no, total_pages)
        nodes = page_result['nodes']
        edges = page_result['edges']
        _scope_ids(prefix, nodes, edges)
        if page_result.get('geometry'):
            from services.geometry_store import link_edges_to_lines, scope_page
            link_edges_to_lines(edges, prefix)
            for n in nodes:
                if n.get('bbox_px'):
                    n.setdefault('bbox_page_w', page_result['geometry']['width'])
                    n.setdefault('bbox_page_h', page_result['geometry']['height'])
            all_geometry.append({'page': page_no,
                                 **scope_page(page_result['geometry'], prefix)})

        # Stamp page identity + dimensions on every node so the page survives
        # the DB round-trip (extra_json) and the frontend can group by it.
        # Drawing label. A real title-block drawing number is globally
        # meaningful, so it is used as-is — two PDFs carrying the same drawing
        # number genuinely are the same sheet.
        #
        # Phase 5: the FALLBACK label was not. "page_1" is only unique within
        # its document, so two PDFs in one project both produced "page_1" and
        # the canvas grouped their symbols into a single drawing cell. The
        # fallback is now scoped by document; single-page documents get a bare
        # "doc{n}" rather than an always-1 page suffix.
        drawing = page_result.get('drawing') or _fallback_drawing(
            source_id, page_no, total_pages)
        for n in nodes:
            n['page'] = page_no
            # Phase 5: page numbers are only unique within their document, so
            # the page identity is (source_id, page). Stamped on the node so
            # the frontend can group by document without a second lookup.
            if source_id is not None:
                n['source_id'] = int(source_id)
            # Phase 3: the raster size this page's normalised coordinates were
            # measured against. Without it the canvas had no way to know a
            # sheet's real aspect ratio and fell back to a fixed 2800x2000
            # cell for every drawing, squashing portrait pages and stretching
            # wide ones. Stamped per node so it rides the existing extra_json
            # path — no schema change, no new table.
            if page_w and page_h:
                n['page_w'] = page_w
                n['page_h'] = page_h
            if drawing and not n.get('drawing'):
                n['drawing'] = drawing

        all_nodes.extend(nodes)
        all_edges.extend(edges)
        all_loops.extend(page_result.get('loops') or [])

        for k in cv_totals:
            cv_totals[k] += page_result['cv'].get(k, 0)
        u = page_result.get('usage') or {}
        usage_total['tokens_in']  += u.get('tokens_in', 0)
        usage_total['tokens_out'] += u.get('tokens_out', 0)
        usage_total['cost_usd']   = round(usage_total['cost_usd'] + u.get('cost_usd', 0.0), 6)
        usage_total['model']      = usage_total['model'] or u.get('model', '')
        usage_total['provider']   = usage_total['provider'] or u.get('provider', '')

        page_reports.append({
            'page': page_no,
            'drawing': drawing,
            'width': page_w,
            'height': page_h,
            'nodes': len(nodes),
            'edges': len(edges),
            'status': page_result['status'],
            'reason': page_result.get('reason'),
        })
        emit({"stage": "page", "status": "complete",
              "page": page_no, "of": total_pages,
              "nodes": len(nodes), "edges": len(edges),
              "page_status": page_result['status'],
              "reason": page_result.get('reason')})

    # ── Roll page statuses up into one run status ─────────────────────────────
    run_status, run_reason = ExtractionStatus.rollup(page_reports)

    if not all_nodes:
        die("Extraction returned 0 nodes across all pages — "
            "check image quality or API key")

    # ── Derive instruments / equipment / connections from the merged pages ────
    instruments, equipment, connections = _derive_studio_tables(all_nodes, all_edges)

    combined_data = {
        'nodes':       all_nodes,
        'edges':       all_edges,
        'instruments': instruments,
        'equipment':   equipment,
        'connections': connections,
        'loops':       all_loops,
        'pages':       page_reports,
        'status':      run_status,
        'reason':      run_reason,
        'cv':          dict(cv_totals),
        'geometry':    all_geometry,
    }

    # Raw LLM output for the whole document, all pages.
    (proj_dir / f'{pid}.json').write_text(
        json.dumps({'nodes': all_nodes, 'edges': all_edges,
                    'pages': page_reports,
                    'status': run_status, 'reason': run_reason},
                   indent=2, ensure_ascii=False),
        encoding='utf-8',
    )

    emit({
        "stage":       "llm_verify",
        "status":      "complete",
        "nodes":       len(all_nodes),
        "instruments": len(instruments),
        "equipment":   len(equipment),
        "connections": len(all_edges),
        "pages":       total_pages,
    })

    _s.cache_store.put(pid, ck0, combined_data, usage_total,
                       file_hash=fhash, pass_num=0)

    persisted = _merge(pid, combined_data, safe_name, fhash, _s, source_id)
    if not persisted and run_status != ExtractionStatus.FAILED:
        run_status, run_reason = ExtractionStatus.PARTIAL, Reason.PERSIST_FAILED

    _finish(pid, _s, cached=False, usage=usage_total,
            status=run_status, reason=run_reason, pages=page_reports)


def _derive_studio_tables(nodes: list, edges: list) -> tuple[dict, dict, list]:
    """Split the merged node/edge lists into the instruments / equipment /
    connections shapes the espx `studio` block and the DB tables expect.

    Unchanged logic, lifted out of the old single-page body so it runs once
    over every page's nodes instead of once per page. Tags are the key here,
    and a tag is plant-unique by convention even when it appears on several
    sheets — so a later page's richer record wins, as before.
    """
    try:
        from adapters.engine import normalize_instrument_type
    except Exception:
        normalize_instrument_type = lambda t: t  # noqa: E731

    instruments: dict = {}
    equipment:   dict = {}
    for node in nodes:
        tag = node.get('label', '')
        if not tag:
            continue
        category = node.get('category', '')
        if category == 'instrument':
            instruments[tag] = {
                'type':          normalize_instrument_type(node.get('type') or node.get('kind', '')),
                'equipment_ref': node.get('equipment_ref'),
                'area':          node.get('area', ''),
                'range_lo':      node.get('range_lo'),
                'range_hi':      node.get('range_hi'),
                'units':         node.get('units'),
                'alarm_lo':      node.get('alarm_lo'),
                'alarm_lolo':    node.get('alarm_lolo'),
                'alarm_hi':      node.get('alarm_hi'),
                'alarm_hihi':    node.get('alarm_hihi'),
                'fail_position': node.get('fail_position'),
                'sil_level':     node.get('sil_level'),
                'loop_number':   node.get('loop_number'),
                'drawing':       node.get('drawing', ''),
                'page':          node.get('page'),
            }
        elif category == 'equipment':
            equipment[tag] = {
                'area':        node.get('area', ''),
                'description': node.get('description', ''),
                'drawing':     node.get('drawing', ''),
                'page':        node.get('page'),
            }

    # Kinds that count as piping rather than instrument signal. The LLM can
    # only emit process/signal/pneumatic (CV_CONNECTIONS_PROMPT line ~654 and
    # _EDGE_SCHEMA agree on that), but edges can also arrive from the editor
    # or an older DB row, so the extra names stay as a tolerant read.
    # Deliberately NOT widened beyond the historic set.
    process_kinds = {'process', 'stream', 'recycle', 'bypass', 'hydraulic'}
    by_id = {n.get('id'): n for n in nodes}
    connections: list = []
    for edge in edges:
        if edge.get('kind', 'process') not in process_kinds:
            continue
        from_node = by_id.get(edge.get('from'), {})
        to_node   = by_id.get(edge.get('to'), {})
        conn_id   = edge.get('line_id') or f"{from_node.get('label','?')}→{to_node.get('label','?')}"
        connections.append({
            'id':         conn_id,
            'from_tag':   from_node.get('label', edge.get('from', '')),
            'to_tag':     to_node.get('label',   edge.get('to',   '')),
            'fluid':      edge.get('fluid'),
            'line_size':  edge.get('line_size'),
            'line_class': edge.get('line_class'),
            'insulation': edge.get('insulation'),
            'to_drawing': edge.get('to_drawing'),
        })
    return instruments, equipment, connections


def _extract_one_page(_s, cv_image_bytes: bytes, page_w: int, page_h: int,
                      page_no: int, total_pages: int, base_name: str,
                      cache_dir: str, provider: str,
                      llm_only: bool) -> dict:
    """Run the full CV + LLM pipeline over ONE rendered page.

    Returns
        {'nodes', 'edges', 'loops', 'drawing', 'cv', 'usage',
         'status', 'reason'}

    This is the body that used to be inlined in run_extraction for the single
    page it processed. Behaviour per page is unchanged; what is new is that
    an LLM stage failure is caught here and turned into a page status instead
    of aborting the whole document, so page 3 failing does not discard pages
    1, 2, 4 and 5.
    """
    # ── The image both LLM stages see: the original, for every provider ──────
    #
    # No downscaling, and no per-provider branch. Resolution is a CORRECTNESS
    # input here, not a bandwidth setting: LLM A identifies symbols from it and
    # LLM B is told to add a connection only when it can see that connection,
    # and P&ID pipes are 1-2px lines.
    #
    # Gemini and Anthropic used to be capped at 3000px, justified as "Gemini's
    # native limit before internal downscale". That cap is why the same drawing
    # extracted correctly on OpenAI and came out with missing connections on
    # Gemini: a 5100x2920 sheet went over at 3000x1718 — a 0.59x linear
    # downscale — so the thin runs, especially the short vessel-to-valve stubs,
    # stopped being resolvable. LLM B correctly declined to add what it could
    # not see, and the geometry stage's gaps survived into the saved graph.
    #
    # Providers that downsample server-side (Claude caps at 1568px whatever it
    # is sent) simply ignore the extra pixels — the cost is bytes on the wire,
    # not accuracy, and these sheets are under 1 MB. If a specific MODEL ever
    # needs a cap, cap it for that model and record where the number came from;
    # capping a whole provider is what caused this.
    llm_image_bytes = cv_image_bytes

    # ── LLM A early-start machinery ───────────────────────────────────────────
    # For the full pipeline: LLM A starts as soon as OCR text is done (while
    # UNet line detection continues). UNet takes ~4 min; LLM A takes ~70s,
    # so LLM A finishes well before UNet — zero extra wait time.
    # LLM B then starts with LLM A's verified symbol types, not raw YOLO types.
    import concurrent.futures as _cf
    import threading as _threading

    _llm_a_future: _cf.Future = _cf.Future()

    def _start_llm_a_from_text(text_result_data, sym_dets, iw, ih):
        """Non-blocking callback: fires LLM A in a background thread."""
        def _worker():
            try:
                sym_sum = _build_symbol_summary(sym_dets, text_result_data.get('texts', []), iw, ih)
                result  = _call_llm_verification(
                    _s, llm_image_bytes, 'image/png', sym_sum,
                    img_w=iw, img_h=ih, raw_lines=[],
                )
                _llm_a_future.set_result(result)
            except Exception as exc:
                _llm_a_future.set_exception(exc)
        _threading.Thread(target=_worker, daemon=True).start()

    # ── CV detection (Symbols → Text + Lines) — each step emits its own row ───
    if llm_only:
        # Fast path: load cached symbol + text + line JSON
        sym_path  = Path(cache_dir) / f'{base_name}_symbol.json'
        text_path = Path(cache_dir) / f'{base_name}_text.json'
        line_path = Path(cache_dir) / f'{base_name}_line.json'
        for p in (sym_path, text_path):
            if not p.exists():
                die(f"--llm-only requires cached files; missing: {p}")
        sym_data  = json.loads(sym_path.read_text(encoding='utf-8'))
        text_data = json.loads(text_path.read_text(encoding='utf-8'))
        sym_dets  = sym_data.get('detections', [])
        sz_raw    = sym_data.get('image_size', {})
        img_w     = sz_raw.get('width', 1) or 1
        img_h     = sz_raw.get('height', 1) or 1
        cached_lines: list = []
        if line_path.exists():
            line_data = json.loads(line_path.read_text(encoding='utf-8'))
            raw = _segs_to_dicts(
                line_data.get('long_lines', []),
                line_data.get('connected_lines', []),
                line_data.get('signal_lines', []),
            )
            cached_lines = _snap_segments_to_symbols(raw, sym_dets)
        cv_results = {
            'symbols':      sym_dets,
            'texts':        text_data.get('texts', []),
            'lines':        cached_lines,
            'image_size':   {'width': img_w, 'height': img_h},
            'symbol_image': str(sym_path),
            'sym_error':    sym_data.get('error'),
            'text_error':   text_data.get('error'),
        }
        emit({"stage": "cv_extracting", "status": "skipped_cached",
              "symbol_count": len(sym_dets),
              "line_count": len(cached_lines)})
        # llm_only: fire LLM A immediately (lines already cached, no wait)
        _start_llm_a_from_text(text_data, sym_dets, img_w, img_h)
    else:
        # Full path: pass callback so LLM A starts the moment text OCR finishes
        cv_results = _run_full_cv(
            cv_image_bytes, base_name, cache_dir,
            on_text_done=_start_llm_a_from_text,
        )

    sz = cv_results['image_size']
    img_w = sz.get('width', 1) or 1
    img_h = sz.get('height', 1) or 1
    raw_lines = cv_results.get('lines', [])
    # Bound here so the page result can always report geometry, including on
    # paths where the connection stage never builds a candidate graph.
    geo_graph = {}

    # Strip point/zero-length segments and bus-intersection stubs before LLM B.
    # These line-detector artifacts have start≈end coordinates or are sub-pixel
    # length touching 5+ symbols (manifold crossing noise).  Each one would
    # appear in the prompt with 6-8 simultaneous node touches, burning the
    # model's reasoning budget before it reaches the real pipe segments.
    raw_lines, _degen_removed = _filter_degenerate_segments(
        raw_lines, cv_results.get('symbols', []), img_w, img_h
    )
    if _degen_removed:
        emit({"stage": "debug",
              "message": f"Filtered {_degen_removed} degenerate segments "
                         f"(point/stub artifacts) — {len(raw_lines)} real segments remain"})

    # ── Phase 3: LLM A already running; wait for it, then run LLM B ─────────
    emit({"stage": "llm_verify", "status": "running",
          "symbols_passed": len(cv_results['symbols']),
          "lines_passed":   len(raw_lines)})

    t1 = datetime.datetime.now()
    page_status = ExtractionStatus.SUCCESS
    page_reason = None
    try:
        llm_a_result, llm_b_result = None, None
        resp_a,       resp_b       = None, None

        # Wait for LLM A (started during UNet; should already be done).
        # LLM A is not optional: nodes are what every later stage attaches
        # to, so a page without them has nothing to salvage. It fails the
        # PAGE, not the run — other pages still extract.
        try:
            llm_a_result, resp_a = _llm_a_future.result()
        except Exception as e:
            emit({"stage": "llm_verify", "status": "failed",
                  "llm_stage": "llm_a_symbols", "page": page_no,
                  "error": str(e)[:300]})
            return _failed_page(ExtractionStatus.FAILED,
                                Reason.SYMBOL_VERIFICATION_FAILED, cv_results)

        # Build LLM B summary from LLM A's verified nodes (correct types + labels)
        # YOLO bboxes are used for spatial touch calculations internally
        conn_summary_text = _build_connection_summary(
            cv_results['symbols'], img_w, img_h,
            lines=raw_lines,
            llm_a_nodes=llm_a_result.get('nodes', []),
        )

        # Save summaries to cache
        sym_summary_text = _build_symbol_summary(
            cv_results['symbols'], cv_results['texts'], img_w, img_h,
        )

        # Build the candidate connectivity graph from geometry alone (no LLM):
        # detected line segments + symbol bboxes, snapped/chained/junction-
        # classified deterministically. LLM B then AUDITS this candidate list
        # (confirm/correct/delete/add) instead of tracing from a blank slate —
        # this session's testing showed blank-slate tracing on a crowded sheet
        # reliably fabricates edges between unrelated pipes and duplicates
        # real pipes as parallel paths; auditing a geometry-backed shortlist
        # avoids both failure modes for anything geometry can resolve.
        _llm_a_nodes_early = llm_a_result.get('nodes', [])
        _early_merge_map: dict[str, str] = {}
        for _n in _llm_a_nodes_early:
            for _absorbed in _n.get('merged_from', []):
                _early_merge_map[_absorbed] = _n.get('id', '')

        # Fallback: LLM A can discard a duplicate YOLO detection as a false/
        # spurious symbol WITHOUT recording it in any surviving node's
        # merged_from — dropping isn't the same as merging in its output
        # schema. Large equipment commonly gets double-detected under two
        # different class labels with near-identical boxes (e.g. a Reactor
        # also detected as "Vessel" or "Tank" a few px off) — any geometry
        # evidence attached to the discarded symbol's raw id then becomes
        # untraceable and gets silently filtered out later, orphaning a real
        # connection that rightfully belonged to the surviving node.
        # Supplement LLM A's explicit merge tracking with our own bbox-
        # overlap check for exactly this case.
        _yolo_bbox_by_id = {f"n{i + 1}": s['bbox'] for i, s in enumerate(cv_results['symbols'])}
        _surviving_ids = {n.get('id', '') for n in _llm_a_nodes_early}
        for _raw_id, _raw_bbox in _yolo_bbox_by_id.items():
            if _raw_id in _surviving_ids or _raw_id in _early_merge_map:
                continue
            _rx1, _ry1, _rx2, _ry2 = _raw_bbox
            _r_area = max(1.0, (_rx2 - _rx1) * (_ry2 - _ry1))
            _best_id, _best_overlap = None, 0.5
            for _sid, _sbbox in _yolo_bbox_by_id.items():
                if _sid == _raw_id or _sid not in _surviving_ids:
                    continue
                _sx1, _sy1, _sx2, _sy2 = _sbbox
                _ix1, _iy1 = max(_rx1, _sx1), max(_ry1, _sy1)
                _ix2, _iy2 = min(_rx2, _sx2), min(_ry2, _sy2)
                if _ix2 > _ix1 and _iy2 > _iy1:
                    _overlap = (_ix2 - _ix1) * (_iy2 - _iy1) / _r_area
                    if _overlap > _best_overlap:
                        _best_overlap, _best_id = _overlap, _sid
            if _best_id is not None:
                _early_merge_map[_raw_id] = _best_id

        # LLM A can add symbols YOLO missed entirely (MISSING-SYMBOL RULES in
        # prompts.py) — these get a fresh id continuing the series but have no
        # YOLO bbox. Left out of the geometry pass, they'd never get a chance
        # to match a line segment at all: same "invisible to the candidate
        # graph" failure as the junction-id bug, just for a different set of
        # nodes. Give each one a synthesized bbox (matching the same fallback
        # _build_connection_summary already uses) and append them, in id
        # order, so build_geometric_connectivity's positional "n{i+1}" ids
        # line up with the ids LLM A actually assigned.
        _orig_symbol_ids = {f"n{i + 1}" for i in range(len(cv_results['symbols']))}
        _added_nodes = sorted(
            (n for n in _llm_a_nodes_early if n.get('id') not in _orig_symbol_ids),
            key=lambda n: int(n.get('id', 'n0')[1:]) if n.get('id', 'n0')[1:].isdigit() else 0,
        )
        _symbols_for_geo = list(cv_results['symbols'])
        for _n in _added_nodes:
            px = _n.get('x', 0.0) * img_w
            py = _n.get('y', 0.0) * img_h
            half = 20
            _symbols_for_geo.append({
                'bbox': [px - half, py - half, px + half, py + half],
                'type': _n.get('type', '?'),
            })

        proposed_graph_text = ''
        geo_graph: dict = {'edges': [], 'junctions': [], 'ambiguous_crossings': [], 'open_stubs': [],
                          'unmatched_symbols': [], 'lines': []}
        try:
            geo_graph = build_geometric_connectivity(_symbols_for_geo, raw_lines)
            # Remap any node id referring to a symbol LLM A merged away, onto
            # the surviving node id, so the audit prompt only ever sees ids
            # that actually exist in the final node list.
            #
            # Junction ids (gj_N) are geometry-only — LLM A never sees or
            # verifies them, so they're never in _llm_a_nodes_early. Without
            # including them here, EVERY edge reaching a real 3+-line
            # junction gets silently dropped from the candidate list before
            # LLM B ever sees it, forcing it to reinvent that connection from
            # the image alone with no segment data to route through — which
            # is exactly what produced a straight-line, geometrically-unrouted
            # edge into a junction instead of the correct pixel-accurate bend.
            _valid_ids = {n['id'] for n in _llm_a_nodes_early} | {
                j['id'] for j in geo_graph.get('junctions', [])
            }
            for _e in geo_graph['edges']:
                _e['from'] = _early_merge_map.get(_e['from'], _e['from'])
                _e['to']   = _early_merge_map.get(_e['to'],   _e['to'])

            # Separate edges that reference an ID LLM A silently discarded
            # (no merge record, not in _valid_ids) from those that are fully
            # resolvable.  The discarded ones would previously vanish here with
            # no trace — UNet detected the pipe, geometry confirmed it, but LLM B
            # never heard about it and couldn't fix what it couldn't see.
            # Instead: salvage the orphaned edge as an open_stub so the dangling
            # line end and its nearest valid neighbour both appear in the audit
            # prompt. LLM B can then confirm the connection via vision under the
            # same 100%-certain discipline it applies to every other stub.
            _kept_edges = []
            _salvaged_stubs = 0
            _geo_lines_for_salvage = geo_graph.get('lines', [])
            for _e in geo_graph['edges']:
                _from_ok = _e['from'] in _valid_ids
                _to_ok   = _e['to']   in _valid_ids
                if _from_ok and _to_ok and _e['from'] != _e['to']:
                    _kept_edges.append(_e)
                    continue
                # At least one end is an orphaned / unknown id — salvage as stub(s).
                # Use the first detected segment endpoint as the dangling pixel pos.
                _line_indices = _e.get('line_indices', [])
                _anchor_line  = _geo_lines_for_salvage[_line_indices[0]] if _line_indices else None
                _far_x = _anchor_line['x2'] if _anchor_line else 0
                _far_y = _anchor_line['y2'] if _anchor_line else 0
                # The surviving (valid) end becomes 'from'; the orphaned end
                # is the dangling pixel we surface for LLM B to look at.
                _valid_anchor = _e['from'] if _from_ok else (_e['to'] if _to_ok else None)
                _orphan_id    = _e['to']   if _from_ok else _e['from']
                # Find the nearest real node to the orphaned end as a candidate hint
                _best_cand, _best_d = None, float('inf')
                for _vn in _llm_a_nodes_early:
                    _vd = math.hypot((_vn.get('x', 0) * img_w) - _far_x,
                                     (_vn.get('y', 0) * img_h) - _far_y)
                    if _vd < _best_d:
                        _best_d, _best_cand = _vd, _vn['id']
                _salvage_stub = {
                    'x': _far_x, 'y': _far_y,
                    'from': _valid_anchor or _best_cand or '',
                    'line_index': _line_indices[0] if _line_indices else 0,
                    '_salvaged_orphan_id': _orphan_id,   # debug only, not sent to LLM
                    '_salvaged_line_indices': _line_indices,  # kept for waypoint routing
                }
                if _best_cand and _best_cand != _valid_anchor:
                    _salvage_stub['candidate_symbol'] = _best_cand
                geo_graph['open_stubs'].append(_salvage_stub)
                _salvaged_stubs += 1

            geo_graph['edges'] = _kept_edges
            for _s_ in geo_graph['open_stubs']:
                if _s_.get('from'):
                    _s_['from'] = _early_merge_map.get(_s_['from'], _s_['from'])
                if _s_.get('candidate_symbol'):
                    _s_['candidate_symbol'] = _early_merge_map.get(
                        _s_['candidate_symbol'], _s_['candidate_symbol'])
            proposed_graph_text = _format_proposed_graph(geo_graph, _llm_a_nodes_early)
            _salvage_note = (f", {_salvaged_stubs} orphaned→stub (UNet saw line, "
                             f"LLM-A silently dropped one endpoint)") if _salvaged_stubs else ""
            emit({"stage": "debug",
                  "message": f"Geometric graph: {len(geo_graph['edges'])} proposed edges, "
                             f"{len(geo_graph['open_stubs'])} candidate stubs, "
                             f"{len(geo_graph['junctions'])} junctions{_salvage_note}"})
        except Exception as _geo_err:
            emit({"stage": "debug",
                  "message": f"Geometric graph build failed (falling back to "
                             f"from-scratch tracing): {_geo_err}"})

        cv_prompt_path = Path(cache_dir) / f'{base_name}_cv_prompt.json'
        cv_prompt_path.write_text(
            json.dumps({'sym_summary': sym_summary_text,
                        'connections_prompt': conn_summary_text,
                        'proposed_graph': proposed_graph_text}, indent=2, ensure_ascii=False),
            encoding='utf-8'
        )
        emit({"stage": "cv_summary", "status": "ok",
              "sym_chars":  len(sym_summary_text),
              "conn_chars": len(conn_summary_text)})

        # Run LLM B — audits the geometric proposal when one was built,
        # otherwise falls back to full from-scratch tracing.
        #
        # LLM B is an AUDITOR over a candidate list that geometry already
        # produced. When it cannot be reached at all, the honest fallback is
        # that unaudited candidate list — not silence. Every such edge is
        # tagged `audited: False` so the review UI and any consumer can tell
        # verified topology from unverified, and the page is reported PARTIAL
        # so the run can never be marked COMPLETE on it.
        try:
            llm_b_result, resp_b = _call_llm_connections(
                _s, llm_image_bytes, 'image/png', conn_summary_text,
                proposed_graph_text,
            )
        except Exception as e:
            emit({"stage": "llm_verify", "status": "degraded",
                  "llm_stage": "llm_b_connections", "page": page_no,
                  "error": str(e)[:300],
                  "fallback_edges": len(geo_graph.get('edges', []))})
            page_status = ExtractionStatus.PARTIAL
            page_reason = Reason.LLM_VERIFICATION_FAILED
            _fallback_edges: list[dict] = []
            for _ge in geo_graph.get('edges', []):
                _fe: dict = {'from': _ge['from'], 'to': _ge['to'],
                             'kind': _ge.get('kind', 'process')}
                _fe['audited'] = False
                _fallback_edges.append(_fe)
            _fallback_junctions: list[dict] = [
                {'id': _j['id'], 'x': _j['x'], 'y': _j['y']}
                for _j in geo_graph.get('junctions', [])
            ]
            llm_b_result = {'edges': _fallback_edges,
                            'junctions': _fallback_junctions}
            resp_b = None

        # ── Merge: nodes from LLM A, edges = Python-proven + LLM B additions ──
        nodes = llm_a_result.get('nodes', [])

        edges = llm_b_result.get('edges', [])

        # Inject T-junction nodes created by LLM B into the node list.
        # Junction nodes MUST carry the same `drawing` label that regular
        # symbol nodes get.  Without it, filteredEdges (CanvasScreen) only
        # sees nodes where n.drawing === current drawing, so a junction with
        # no drawing field is invisible — and every edge that passes through
        # it is silently dropped before React Flow even sees it.
        # page_drawing is available at this scope (set at line ~981 below,
        # but we need it here). We use llm_a_result's drawing block as the
        # same source of truth that sets page_drawing later.
        _drw_for_junction = ''
        _drw_block = llm_a_result.get('drawing') if llm_a_result else None
        if isinstance(_drw_block, dict):
            _drw_for_junction = str(_drw_block.get('number') or '').strip()
        for jn in llm_b_result.get('junctions', []):
            jid = jn.get('id', '')
            if jid and not any(n.get('id') == jid for n in nodes):
                nodes.append({
                    'id':       jid,
                    'type':     'junction',
                    'kind':     'junction',
                    'category': 'junction',
                    'label':    '',
                    'x':        jn.get('x', 0.0),
                    'y':        jn.get('y', 0.0),
                    'confidence': 1.0,
                    'drawing':  _drw_for_junction,
                })

        # Build merge map: absorbed node id → surviving node id
        # (LLM A may have merged duplicate symbols)
        merge_map: dict[str, str] = {}
        for node in nodes:
            surviving = node.get('id', '')
            for absorbed in node.get('merged_from', []):
                merge_map[absorbed] = surviving

        # Remap edge endpoints through merge map and update waypoints
        # using LLM A's verified node positions
        verified_positions = {n['id']: n for n in nodes}
        for edge in edges:
            edge['from'] = merge_map.get(edge['from'], edge['from'])
            edge['to']   = merge_map.get(edge['to'],   edge['to'])
            # Re-anchor waypoints to verified symbol positions
            src = verified_positions.get(edge['from'])
            dst = verified_positions.get(edge['to'])
            if src and dst and edge.get('waypoints'):
                wps = edge['waypoints']
                wps[0]  = [round(src['x'], 4), round(src['y'], 4)]
                wps[-1] = [round(dst['x'], 4), round(dst['y'], 4)]

        # Route every KEPT edge along the real detected pixels, not a straight
        # line — this is what makes the canvas render pipe bends matching the
        # actual source diagram. Fully code-driven: the geometric candidate
        # graph already recorded which raw line segments make up each proposed
        # edge, so we chain those segments' real pixel coordinates whenever the
        # LLM's edge matches a proposal (in either direction). LLM-added edges
        # with no geometric backing (junction taps, unmatched-symbol adds) have
        # no detected pixels to route through, so they keep a straight line —
        # the honest best available given no segment data exists for them.
        _geo_edge_by_pair = {
            frozenset((_e['from'], _e['to'])): _e['line_indices']
            for _e in geo_graph.get('edges', [])
        }
        # Extend with salvaged-stub pairs: these were real geo edges whose one
        # endpoint was orphaned. If LLM B confirms the connection (adds the
        # edge), we can still route it through the real detected pixel path.
        for _ss in geo_graph.get('open_stubs', []):
            _ss_li = _ss.get('_salvaged_line_indices')
            _ss_fr = _ss.get('from', '')
            _ss_ca = _ss.get('candidate_symbol', '')
            if _ss_li and _ss_fr and _ss_ca:
                _salvaged_pair = frozenset((_ss_fr, _ss_ca))
                if _salvaged_pair not in _geo_edge_by_pair:
                    _geo_edge_by_pair[_salvaged_pair] = _ss_li
        for edge in edges:
            if edge.get('waypoints'):
                continue  # already has LLM-A-style seg-id waypoints (rare for LLM B)
            src = verified_positions.get(edge['from'])
            dst = verified_positions.get(edge['to'])
            if not (src and dst):
                continue
            line_idx = _geo_edge_by_pair.get(frozenset((edge['from'], edge['to'])))
            if line_idx:
                # Persisted as line_ids by run_extraction, so the connectivity
                # export can tie this edge to its drawn pipe run.
                edge['line_indices'] = list(line_idx)
                # line_idx indexes into geo_graph['lines'] (possibly split at
                # T-taps), NOT the original raw_lines — they can differ in
                # length/order after _split_lines_at_taps.
                edge['waypoints'] = _chain_pixel_segments(
                    line_idx, geo_graph.get('lines', raw_lines), img_w, img_h,
                    src['x'], src['y'], dst['x'], dst['y'],
                )
            else:
                # No geometric segment data available (LLM-added edge from
                # unmatched symbol or ambiguous crossing). Emit a minimal
                # 2-point waypoints so the frontend knows this is an extracted
                # straight line rather than a user-dragged bend, and can anchor
                # it to the correct symbol handle faces.
                edge['waypoints'] = [
                    [round(src['x'], 4), round(src['y'], 4)],
                    [round(dst['x'], 4), round(dst['y'], 4)],
                ]

        # ── Provenance + geometry-first enforcement (Phase 2) ────────────────
        # The pipeline's contract is that deterministic geometry establishes
        # topology and the LLM audits it. That contract lived only in the
        # prompt, so an LLM-added edge between two symbols geometry never saw
        # any evidence for was indistinguishable from a confirmed one.
        #
        # Every kept edge is now stamped with how it was established:
        #   'geometry'  proposed by connectivity_graph and confirmed by LLM B
        #   'llm'       added by LLM B against a stub / unmatched symbol /
        #               ambiguous crossing that geometry explicitly surfaced
        # and an LLM add with NO grounding of any kind is dropped, because
        # geometry did look at that pair and found nothing to look at.
        _grounded_ids = set(geo_graph.get('unmatched_symbols', []))
        for _s_ in geo_graph.get('open_stubs', []):
            if _s_.get('from'):
                _grounded_ids.add(_s_['from'])
            if _s_.get('candidate_symbol'):
                _grounded_ids.add(_s_['candidate_symbol'])
        # A junction the geometry created is itself evidence: LLM B is expected
        # to wire real taps through it.
        _grounded_ids |= {j['id'] for j in geo_graph.get('junctions', [])}
        # An unresolved segment is a REAL detected line that reached neither a
        # symbol nor a junction, so no edge could be built from it. Both of its
        # candidate endpoints are grounded: a detected line is exactly the kind
        # of evidence this filter exists to require, and without this an add
        # against one would be discarded for having "no grounding" while the
        # segment sat right there in the prompt.
        for _u_ in geo_graph.get('unreached_segments', []):
            for _k_ in ('candidate_from', 'candidate_to'):
                if _u_.get(_k_):
                    _grounded_ids.add(_u_[_k_])
        # A junction LLM B created for a tap splice. The connections prompt
        # explicitly instructs it to do this: "you may CREATE A NEW JUNCTION at
        # the tap point (assign it a fresh id like gj_new_1) and then add the
        # two/three edges that meet there ... To splice a tap, you MUST delete
        # the original continuous pipe edge and replace it with two segments
        # meeting at the new junction."
        #
        # A splice is therefore ONE instruction producing three edges: the tap
        # into the junction, and the host pipe cut in half through it. Nothing
        # grounded those: the new junction is an id the model invented, and the
        # two host symbols are already matched, so neither end was in this set.
        # The tap edge survived only when the instrument happened to be an
        # unmatched symbol, and the two halves of the host pipe were dropped —
        # leaving a junction wired to the instrument and to nothing else.
        #
        # Measured on p-id-1: five gj_new_* junctions, all with degree 0 or 1,
        # every one of them a half-applied splice. gj_new_4 is the floating dot
        # under PI 1017 with PCV 1016 and its ball valve left unconnected.
        #
        # Accepting one edge of a splice while discarding the other two is
        # worse than accepting or rejecting all three, so the junction the
        # model declared grounds the edges that meet at it.
        _grounded_ids |= {str(j['id']) for j in llm_b_result.get('junctions', [])
                          if _is_llm_junction(j.get('id'))}
        # An ambiguous crossing is a place geometry deliberately refused to
        # decide, so an edge there is a legitimate LLM call.
        _has_ambiguous = bool(geo_graph.get('ambiguous_crossings'))

        _kept, _ungrounded = [], []
        for edge in edges:
            pair = frozenset((edge.get('from'), edge.get('to')))
            if pair in _geo_edge_by_pair:
                edge['provenance'] = 'geometry'
                _kept.append(edge)
                continue
            if (edge.get('from') in _grounded_ids or edge.get('to') in _grounded_ids
                    or _has_ambiguous or not geo_graph.get('edges')):
                # The last clause keeps the from-scratch mode working: when
                # geometry produced no candidate graph at all (no UNet
                # segments), there is nothing for an add to be grounded
                # against and the LLM is the only source available.
                edge['provenance'] = 'llm'
                _kept.append(edge)
                continue
            _ungrounded.append(edge)

        if _ungrounded:
            emit({"stage": "debug",
                  "message": f"Dropped {len(_ungrounded)} LLM edge(s) with no "
                             f"geometric grounding (no segment, stub, junction "
                             f"or ambiguous crossing near either endpoint)",
                  "dropped_pairs": [f"{e.get('from')}-{e.get('to')}"
                                    for e in _ungrounded[:20]]})
        edges = _kept

        # A junction joins things. One left with fewer than two edges joins
        # nothing, and renders on the canvas as a dot floating in space with a
        # single line dangling off it — which is what a half-applied splice
        # used to leave behind. Geometry's own junctions are built from 3+
        # meeting lines and are unaffected; this only sweeps up an LLM-created
        # junction whose splice did not survive for some other reason.
        _deg: dict[str, int] = {}
        for e in edges:
            _deg[e.get('from')] = _deg.get(e.get('from'), 0) + 1
            _deg[e.get('to')]   = _deg.get(e.get('to'), 0) + 1
        # A junction joining exactly TWO things is not a junction — it is a
        # bend in one pipe, and the pipe should be a single edge. Geometry
        # never makes these (a cluster needs 3+ meeting lines to qualify), but
        # LLM B does: on a real run every one of the ten tanks was wired
        # Tank -> gj_new_N -> Ball_Valve, two edges and an invented node where
        # one direct edge belongs. Collapse them back to the direct edge.
        _collapsed = 0
        for _j_ in list(llm_b_result.get('junctions', [])):
            jid = str(_j_.get('id') or '')
            if not _is_llm_junction(jid) or _deg.get(jid, 0) != 2:
                continue
            _pair = [e for e in edges if e.get('from') == jid or e.get('to') == jid]
            if len(_pair) != 2:
                continue
            _ends = [e['to'] if e['from'] == jid else e['from'] for e in _pair]
            if _ends[0] == _ends[1]:
                continue                      # self-loop through the junction
            _kinds = {e.get('kind', 'process') for e in _pair}
            edges = [e for e in edges if e not in _pair]
            edges.append({'from': _ends[0], 'to': _ends[1],
                          'kind': 'signal' if 'signal' in _kinds else 'process',
                          'provenance': 'llm'})
            llm_b_result['junctions'] = [x for x in llm_b_result.get('junctions', [])
                                         if str(x.get('id')) != jid]
            _deg[_ends[0]] = _deg.get(_ends[0], 1)
            _deg[_ends[1]] = _deg.get(_ends[1], 1)
            _deg[jid] = 0
            _collapsed += 1
        if _collapsed:
            emit({"stage": "debug",
                  "message": f"Collapsed {_collapsed} two-way LLM junction(s) "
                             f"into a direct symbol-to-symbol edge"})

        _dead = [str(j['id']) for j in llm_b_result.get('junctions', [])
                 if _is_llm_junction(j.get('id'))
                 and _deg.get(str(j.get('id', '')), 0) < 2]
        if _dead:
            emit({"stage": "debug",
                  "message": f"Dropped {len(_dead)} LLM junction(s) joining "
                             f"fewer than two edges",
                  "dead_junctions": _dead[:20]})
            _dead_set = set(_dead)
            llm_b_result['junctions'] = [
                j for j in llm_b_result.get('junctions', [])
                if j.get('id') not in _dead_set
            ]
            edges = [e for e in edges
                     if e.get('from') not in _dead_set and e.get('to') not in _dead_set]

        # Code-level backstop for two known cross-stage contradictions the LLM
        # sometimes produces (the connections prompt says not to do these, but
        # compliance isn't guaranteed since verify/connections are separate calls):
        #
        # 1. isolated_reason nodes (text labels, legend icons, false positives —
        #    confirmed NOT a real symbol) must never carry an edge. Any such
        #    edge is fabricated; drop it.
        #
        # 2. equipment_ref is a *guess* made by the verify stage, before it has
        #    seen any line-segment data, that a node is a floating label with
        #    no piping of its own. If the connections stage — which does see
        #    the segments — actually traces a real edge to that node, the
        #    segment evidence overrides the earlier guess: clear equipment_ref
        #    rather than dropping the edge, since the pipe is real.
        # isolated_reason is a verify-stage GUESS, made before any line-segment
        # data exists — exactly like equipment_ref below. When the connections
        # stage, which sees both the image and the geometry, traces a real pipe
        # into a node YOLO classified as physical equipment, that later evidence
        # wins: clear the flag rather than delete the pipe.
        #
        # Measured on p-id-1: LLM A flagged all ten tanks "text label, not a
        # symbol" — the tanks are drawn as an outline with the service name
        # (N2, C02, C2H4 C2H6) inside, which reads like a boxed label. LLM B
        # connected them correctly anyway, and this rule then deleted all ten
        # edges, leaving every tank on the sheet unpiped.
        #
        # No list of "real" kinds is needed, and none is kept: the evidence
        # decides. A pipe traced INTO a node is proof the node is a symbol, so
        # any flagged node an edge reaches has its flag cleared — the same test
        # equipment_ref uses below. A genuine text label attracts no pipe, so
        # it keeps its flag and its fabricated edges are still dropped.
        _isolated_ids = {n['id'] for n in nodes if n.get('isolated_reason')}
        if _isolated_ids:
            _touched = {e['from'] for e in edges} | {e['to'] for e in edges}
            _overturned = _isolated_ids & _touched
            if _overturned:
                for node in nodes:
                    if node['id'] in _overturned:
                        node.pop('isolated_reason', None)
                emit({"stage": "debug",
                      "message": f"Cleared isolated_reason on {len(_overturned)} "
                                 f"node(s) the connections stage traced a real "
                                 f"pipe to",
                      "overturned": sorted(_overturned)[:20]})
                _isolated_ids -= _overturned

            _before = len(edges)
            edges = [e for e in edges
                     if e['from'] not in _isolated_ids and e['to'] not in _isolated_ids]
            if len(edges) != _before:
                emit({"stage": "debug",
                      "message": f"Dropped {_before - len(edges)} edge(s) touching "
                                 f"isolated_reason nodes"})

        _connected_ids = {e['from'] for e in edges} | {e['to'] for e in edges}
        _cleared = 0
        for node in nodes:
            if node.get('equipment_ref') and node['id'] in _connected_ids:
                node.pop('equipment_ref')
                _cleared += 1
        if _cleared:
            emit({"stage": "debug",
                  "message": f"Cleared equipment_ref on {_cleared} node(s) that "
                             f"turned out to have real pipe connections"})

        verified = {**llm_a_result, 'edges': edges}

    except SystemExit:
        raise
    except Exception as e:
        emit({"stage": "llm_verify", "status": "failed", "page": page_no,
              "error": str(e)[:300]})
        return _failed_page(ExtractionStatus.FAILED,
                            Reason.SYMBOL_VERIFICATION_FAILED, cv_results)

    verify_elapsed = round((datetime.datetime.now() - t1).total_seconds(), 1)

    nodes  = verified.get('nodes', [])
    edges  = verified.get('edges', [])
    loops  = verified.get('loops', [])

    if not nodes:
        emit({"stage": "llm_verify", "status": "failed", "page": page_no,
              "error": "LLM verification returned 0 nodes"})
        return _failed_page(ExtractionStatus.FAILED,
                            Reason.SYMBOL_VERIFICATION_FAILED, cv_results)

    # The per-page drawing identity. `drawing.number` is declared in
    # CV_VERIFY_OUTPUT_SCHEMA and the model fills it from the title block, but
    # nothing ever read it — so `drawing` stayed empty on every node and the
    # multi-drawing grouping downstream was dead. Read it now, and fall back
    # to a synthetic page label for multi-page documents so pages still
    # separate when the title block is unreadable.
    page_drawing = ''
    _drw = verified.get('drawing')
    if isinstance(_drw, dict):
        page_drawing = str(_drw.get('number') or '').strip()

    # ── Restore exact YOLO coordinates ────────────────────────────────────────
    # The LLM sometimes rounds or re-estimates positions. For every YOLO-detected
    # node (id = "nN" where N = bracket index in cv_summary), overwrite x,y with
    # the precise bounding-box centre from the original YOLO detections.
    # LLM-added nodes (id continues past the YOLO count) keep their LLM estimate.
    _img_w = sz.get('width', 1) or 1
    _img_h = sz.get('height', 1) or 1
    _yolo_syms = cv_results.get('symbols', [])
    _yolo_coords: dict[str, tuple[float, float]] = {}
    for _i, _sym in enumerate(_yolo_syms):
        _bb = _sym.get('bbox', [0, 0, 0, 0])
        _cx = round((_bb[0] + _bb[2]) / 2 / _img_w, 4)
        _cy = round((_bb[1] + _bb[3]) / 2 / _img_h, 4)
        _yolo_coords[f'n{_i + 1}'] = (_cx, _cy)
    for _node in nodes:
        _nid = _node.get('id', '')
        if _nid in _yolo_coords:
            _node['x'], _node['y'] = _yolo_coords[_nid]

    # ── Snap edge waypoints to exact symbol bbox edges ────────────────────────
    # Direction-aware snap: uses pipe travel direction to pick the correct
    # exit/entry edge of the symbol bbox so pipes connect flush at the right side.
    _yolo_bboxes: dict[str, tuple] = {}
    for _i, _sym in enumerate(_yolo_syms):
        _bb = _sym.get('bbox', [0, 0, 0, 0])
        _yolo_bboxes[f'n{_i + 1}'] = (
            round(_bb[0] / _img_w, 4), round(_bb[1] / _img_h, 4),
            round(_bb[2] / _img_w, 4), round(_bb[3] / _img_h, 4),
        )

    def _snap_start(wp, bbox, next_wp):
        """Snap first waypoint to the bbox edge the pipe exits toward next_wp."""
        x, y = float(wp[0]), float(wp[1])
        x1, y1, x2, y2 = bbox
        nx, ny = float(next_wp[0]), float(next_wp[1])
        dx, dy = nx - x, ny - y
        if abs(dx) >= abs(dy):          # horizontal pipe
            return [x2, y] if dx >= 0 else [x1, y]
        else:                           # vertical pipe
            return [x, y2] if dy >= 0 else [x, y1]

    def _snap_end(wp, bbox, prev_wp):
        """Snap last waypoint to the bbox edge the pipe arrives from prev_wp."""
        x, y = float(wp[0]), float(wp[1])
        x1, y1, x2, y2 = bbox
        px, py = float(prev_wp[0]), float(prev_wp[1])
        dx, dy = x - px, y - py
        if abs(dx) >= abs(dy):          # horizontal pipe
            return [x1, y] if dx >= 0 else [x2, y]
        else:                           # vertical pipe
            return [x, y1] if dy >= 0 else [x, y2]

    for _e in edges:
        _wps = _e.get('waypoints')
        if not _wps or len(_wps) < 2:
            continue
        _from_bbox = _yolo_bboxes.get(_e.get('from', ''))
        _to_bbox   = _yolo_bboxes.get(_e.get('to', ''))
        if _from_bbox:
            _wps[0]  = _snap_start(_wps[0], _from_bbox, _wps[1])
        if _to_bbox:
            _wps[-1] = _snap_end(_wps[-1], _to_bbox, _wps[-2])

    emit({
        "stage":       "llm_verify",
        "status":      "complete",
        "page":        page_no,
        "nodes":       len(nodes),
        "connections": len(edges),
        "elapsed_s":   verify_elapsed,
    })

    # Per-page usage from LLM A (symbols) and LLM B (connections).
    # resp_b is None when LLM B failed and geometry supplied the fallback.
    def _tokens(r): return int(getattr(r, 'input_tokens', 0) or 0), int(getattr(r, 'output_tokens', 0) or 0)
    a_in, a_out = _tokens(resp_a) if resp_a else (0, 0)
    b_in, b_out = _tokens(resp_b) if resp_b else (0, 0)
    usage = {
        'tokens_in':  a_in  + b_in,
        'tokens_out': a_out + b_out,
        'cost_usd':   round(
            (getattr(resp_a, 'cost_usd', 0.0) or 0.0) +
            (getattr(resp_b, 'cost_usd', 0.0) or 0.0), 6
        ),
        'model':    getattr(resp_a, 'model', '') or getattr(resp_b, 'model', ''),
        'provider': getattr(resp_a, 'provider', '') or getattr(resp_b, 'provider', ''),
    }

    # Flow arrows and heat tracing: a separate pass, because the line tracer
    # records neither (services/llm_flow_annotation_service.py).
    _annotations = None
    from services.llm_flow_annotation_service import detect_flow_annotations, enabled as _flow_on
    if _flow_on():
        try:
            _annotations = detect_flow_annotations(_s, cv_image_bytes)
            for _r in _annotations.get('usage') or []:
                usage['tokens_in'] += int(getattr(_r, 'input_tokens', 0) or 0)
                usage['tokens_out'] += int(getattr(_r, 'output_tokens', 0) or 0)
                usage['cost_usd'] = round(usage['cost_usd'] + (getattr(_r, 'cost_usd', 0.0) or 0.0), 6)
            emit({"stage": "flow_annotations", "status": "complete", "page": page_no,
                  "arrows": len(_annotations['arrows']),
                  "heat_trace_segments": len(_annotations['heat_trace']),
                  "failed_crops": _annotations['failed']})
        except Exception as _exc:
            emit({"stage": "flow_annotations", "status": "failed", "page": page_no,
                  "error": str(_exc)[:200]})

    from services.geometry_store import page_geometry, stamp_symbol_bboxes
    _geometry = page_geometry(geo_graph, cv_results.get('symbols'), img_w, img_h, _annotations)
    stamp_symbol_bboxes(nodes, _geometry)

    return {
        'geometry': _geometry,
        'nodes':   nodes,
        'edges':   edges,
        'loops':   loops,
        'drawing': page_drawing,
        'status':  page_status,
        'reason':  page_reason,
        'usage':   usage,
        'cv': {
            'symbol_count': len(cv_results['symbols']),
            'text_count':   len(cv_results['texts']),
            'line_count':   len(cv_results.get('lines', [])),
        },
    }


def _failed_page(status: str, reason: str, cv_results: dict | None = None) -> dict:
    """A page result carrying no topology, in the shape run_extraction expects.

    Keeps the CV counts so the progress log still shows what detection found
    before the LLM stage gave out — useful for telling "the sheet was blank"
    apart from "the model was unreachable".
    """
    cv_results = cv_results or {}
    return {
        'nodes': [], 'edges': [], 'loops': [], 'drawing': '',
        'status': status, 'reason': reason,
        'usage': {'tokens_in': 0, 'tokens_out': 0, 'cost_usd': 0.0,
                  'model': '', 'provider': ''},
        'cv': {
            'symbol_count': len(cv_results.get('symbols', [])),
            'text_count':   len(cv_results.get('texts', [])),
            'line_count':   len(cv_results.get('lines', [])),
        },
    }


_KIND_TO_CATEGORY = {
    'vessel': 'equipment', 'reactor': 'equipment', 'heat_exchanger': 'equipment',
    'pump': 'equipment', 'compressor': 'equipment', 'column': 'equipment',
    'absorber': 'equipment', 'heater': 'equipment',
    'vendor_package': 'equipment', 'package': 'equipment',
    'indicator': 'instrument', 'transmitter': 'instrument', 'controller': 'instrument',
    'switch': 'instrument', 'alarm': 'instrument', 'element': 'instrument',
    'meter': 'instrument', 'analyzer': 'instrument', 'analyser': 'instrument',
    'hand_valve': 'mechanical', 'control_valve': 'mechanical', 'solenoid_valve': 'mechanical',
    'relief_valve': 'mechanical', 'check_valve': 'mechanical', 'valve': 'mechanical',
    'fitting': 'mechanical', 'quick_connect': 'mechanical',
    'off_page_connector': 'connector', 'connector': 'connector',
}


#: A row an engineer or a Describe agent authored, never produced by extraction.
#: Python agent writes mark extra_json origin="authored"; the desktop app's
#: Describe path marks nodes the same way, and its older rows carry
#: drawing="DESCRIBE" on edges. Re-extraction must carry every such row forward,
#: whatever document is being re-extracted, or the engineer's retrofit is lost.
#: The same markers the database's origin triggers read (adapters/db.py
#: ORIGIN_SQL). Matched on extra_json rather than the origin column because
#: extraction can run against a hub that has not been migrated yet.
_AUTHORED_SQL = ("(extra_json LIKE '%\"origin\": \"authored\"%' "
                 "OR extra_json LIKE '%\"origin\":\"authored\"%' "
                 "OR extra_json LIKE '%\"source\": \"describe_agent\"%' "
                 "OR extra_json LIKE '%\"source\":\"describe_agent\"%' "
                 "OR extra_json LIKE '%\"drawing\": \"DESCRIBE\"%' "
                 "OR extra_json LIKE '%\"drawing\":\"DESCRIBE\"%')")


def _rows_from_other_sources(pid: str, source_id: int | None) -> tuple[list, list]:
    """Nodes and edges already in the project that belong to a DIFFERENT document.

    Phase 5. _db_persist_espx rewrites a project wholesale (DELETE ... WHERE
    pid = ?, then re-insert), so whatever is not in the espx handed to it is
    gone. Carrying the other documents' rows forward is what makes extracting
    PDF B leave PDF A's data alone.

    Legacy rows (source_id IS NULL, written before this migration) are carried
    forward too — they belong to the project, just to no known document, and
    dropping them would be exactly the data loss this phase exists to stop.
    Only rows matching `source_id` are excluded, because this run is replacing
    them.

    With no `source_id` the rule inverts: the run owns the unattributed rows
    and nothing else, so every attributed row is preserved. See the branch
    below.
    """
    from adapters import db as _db
    conn = _db.get_db()

    if source_id is None:
        # A run with no document identity (the Flask path, or the CLI invoked
        # without --source-id) cannot own rows that DO belong to a document, so
        # every attributed row is carried forward and only the unattributed
        # rows are replaced. Returning nothing here instead — as this function
        # first did — meant such a run wiped every document in the project,
        # because _db_persist_espx deletes the whole project before
        # re-inserting. That is the Phase 5 failure mode reappearing through
        # the back door, and it destroyed BOTH documents in a two-PDF project.
        node_sql = ('SELECT id, pid, kind, kind_detail, label, area, x, y, extra_json, source_id '
                    'FROM nodes WHERE pid = ? AND (source_id IS NOT NULL OR ' + _AUTHORED_SQL + ')')
        edge_sql = ('SELECT from_id, to_id, kind, label, extra_json, source_id '
                    'FROM edges WHERE pid = ? AND (source_id IS NOT NULL OR ' + _AUTHORED_SQL + ')')
        params: tuple = (pid,)
    else:
        node_sql = ('SELECT id, pid, kind, kind_detail, label, area, x, y, extra_json, source_id '
                    'FROM nodes WHERE pid = ? AND (source_id IS NULL OR source_id != ?)')
        edge_sql = ('SELECT from_id, to_id, kind, label, extra_json, source_id '
                    'FROM edges WHERE pid = ? AND (source_id IS NULL OR source_id != ?)')
        params = (pid, int(source_id))

    node_rows = conn.execute(node_sql, params).fetchall()
    edge_rows = conn.execute(edge_sql, params).fetchall()

    nodes = []
    for r in node_rows:
        n = dict(json.loads(r[8]) if r[8] else {})
        n.update({'id': r[0], 'kind': r[2], 'kind_detail': r[3], 'label': r[4],
                  'area': r[5], 'x': r[6], 'y': r[7]})
        if r[9] is not None:
            n['source_id'] = r[9]
        nodes.append(n)

    edges = []
    for r in edge_rows:
        e = dict(json.loads(r[4]) if r[4] else {})
        e.update({'from': r[0], 'to': r[1], 'kind': r[2], 'label': r[3]})
        if r[5] is not None:
            e['source_id'] = r[5]
        edges.append(e)
    return nodes, edges


def _merge(pid: str, combined_data: dict, filename: str, fhash: str, _s,
           source_id: int | None = None) -> bool:
    """Write this extraction's data into the project without disturbing the
    other documents already in it.

    Returns True when the write is visible in the DB afterwards. Phase 1:
    previously returned None and the caller could not tell a silent rollback
    from a good write.

    Phase 5: this used to say "always start fresh — no accumulation across
    runs" and hand _db_persist_espx only the current run's nodes. Since that
    function deletes the whole project before re-inserting, extracting a
    second PDF into a project DELETED the first PDF's nodes and edges
    outright — no id collision required. Rows from other documents are now
    read back and carried through.
    """
    emit({"stage": "merge", "status": "running"})

    kept_nodes, kept_edges = _rows_from_other_sources(pid, source_id)

    run_nodes = combined_data.get('nodes', [])
    run_edges = combined_data.get('edges', [])
    for n in run_nodes:
        if source_id is not None:
            n['source_id'] = int(source_id)
    for e in run_edges:
        if source_id is not None:
            e['source_id'] = int(source_id)

    new_nodes = kept_nodes + run_nodes
    new_edges = kept_edges + run_edges

    # Guarantee every node has 'type' and 'category' — LLMs sometimes omit them.
    # type     = raw YOLO class (falls back to label when LLM merged/renamed)
    # category = derived from type (preferred) or kind when missing
    for n in new_nodes:
        if not n.get('type'):
            n['type'] = n.get('label', 'Unknown')
        if not n.get('category'):
            lookup = (n.get('type') or n.get('kind', '')).lower()
            n['category'] = _KIND_TO_CATEGORY.get(lookup) or _KIND_TO_CATEGORY.get(n.get('kind', ''), 'mechanical')
    new_drawings = sorted({n.get('drawing', '') for n in new_nodes if n.get('drawing')})

    espx = {
        'nodes': new_nodes,
        'edges': new_edges,
        'meta': {'mermaid': ''},
        'studio': {
            'metadata':    {'plant_name': pid, 'process_type': 'generic'},
            'instruments': combined_data.get('instruments', {}),
            'equipment':   combined_data.get('equipment', {}),
            'connections': combined_data.get('connections', []),
            'screens':     [],
            'review':      {},
            'loops':       {l['key']: l for l in combined_data.get('loops', []) if l.get('key')},
        }
    }

    # Instruments/equipment/connections are project-level aggregates keyed by
    # tag, so they have to be re-derived over every document in the project.
    # Deriving them from this run alone would drop the other documents' tags
    # from the Review and Export screens even though their nodes survived.
    if kept_nodes or kept_edges:
        instruments, equipment, connections = _derive_studio_tables(new_nodes, new_edges)
        espx['studio']['instruments'] = instruments
        espx['studio']['equipment']   = equipment
        espx['studio']['connections'] = connections

    mermaid = _s.generate_mermaid_python({'nodes': new_nodes, 'edges': new_edges})
    espx['meta']['mermaid'] = mermaid
    espx['meta']['confidence'] = 'high'

    _s._db_persist_espx(pid, espx)

    # Geometry is keyed by document, so this replaces only this document's
    # rows; other documents' geometry stays untouched. A failure here must not
    # fail the extraction: nodes and edges are already persisted.
    if combined_data.get('geometry') is not None:
        try:
            from services.geometry_store import persist_pages
            stored = persist_pages(pid, source_id, combined_data['geometry'])
            emit({"stage": "geometry", "status": "complete", **stored})
        except Exception as _geo_err:
            emit({"stage": "geometry", "status": "failed", "message": str(_geo_err)[:200]})

    # _db_persist_espx catches its own exceptions and rolls back, returning
    # normally — so a failed write is indistinguishable from a successful one
    # at the call site. Read the row count back and let the caller downgrade
    # the run to PARTIAL/PERSIST_FAILED rather than reporting a clean run over
    # a database that took none of it.
    from adapters import db as _db
    persisted_nodes = _db.get_db().execute(
        'SELECT COUNT(*) FROM nodes WHERE pid = ?', (pid,)
    ).fetchone()[0]
    persisted = (persisted_nodes > 0) or not new_nodes
    if not persisted:
        emit({"stage": "merge", "status": "failed",
              "message": f"expected {len(new_nodes)} nodes in the DB, found 0"})

    _db.get_db().execute(
        'INSERT INTO sources (pid, filename, file_hash, uploaded, cached) '
        'SELECT ?, ?, ?, datetime(\'now\'), 1 '
        'WHERE NOT EXISTS (SELECT 1 FROM sources WHERE pid = ? AND filename = ?)',
        (pid, filename, fhash, pid, filename)
    )

    instruments = combined_data.get('instruments', {})
    equipment   = combined_data.get('equipment', {})
    _s.update_manifest_after_extract(
        pid, filename, fhash,
        len(espx['nodes']), len(instruments), len(equipment),
        len(espx['edges']), drawings=new_drawings
    )

    emit({"stage": "merge", "status": "complete",
          "new_nodes": len(new_nodes), "new_edges": len(new_edges),
          "new_drawings": new_drawings or ['(none)']})
    return persisted


def _finish(pid: str, _s, cached: bool, usage: dict | None = None,
            status: str = ExtractionStatus.SUCCESS,
            reason: str | None = None,
            pages: list | None = None) -> None:
    """Emit the final 'done' event with totals read from the merged espx.

    `status`/`reason`/`pages` are new in Phase 1. The Tauri shell keys the
    source's COMPLETE flag off `status` now, so a PARTIAL run stays visibly
    partial instead of being counted as a finished extraction.
    """
    espx, _ = _s.load_espx(pid)
    studio   = espx.get('studio', {})
    event: dict = {
        "stage":             "done",
        "cached":            cached,
        "status":            status,
        "reason":            reason,
        "total_pages":       len(pages) if pages is not None else 1,
        "total_nodes":       len(espx.get('nodes', [])),
        "total_instruments": len(studio.get('instruments', {})),
        "total_equipment":   len(studio.get('equipment', {})),
        "total_connections": len(espx.get('edges', [])),
    }
    if pages is not None:
        event["pages"] = pages
    if usage:
        event["usage"] = usage
    emit(event)
