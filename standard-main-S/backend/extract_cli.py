"""
extract_cli.py — CV-first + LLM verification pipeline for EngineeringStudio.

Phase 11: this file's implementation was decomposed into the extraction_cli/
package (see extraction_cli/__init__.py for the module map). This file
remains a real script (not replaced by a package) because it's spawned
directly by the Tauri desktop sidecar as `python extract_cli.py <hub> <pid>
<pdf>` (see CLAUDE.md) — turning it into a directory would break that
invocation. It's now a thin compatibility shim: same CLI, same behavior,
same `from extract_cli import X` surface for existing importers
(tests/test_snap_segments.py imports `_snap_segments_to_symbols`).

Usage
-----
    cd C:\\standard\\studio
    python extract_cli.py <hub_path> <pid> <pdf_or_image_path>

Configuration
-------------
    LLM provider, API key(s), and model — chosen from the app's Settings
    screen and read from the `settings` table in studio.db (see
    adapters/config.py). No environment-variable configuration is supported.
"""
from __future__ import annotations

from extraction_cli import (
    emit, die,
    _render_pdf_to_png,
    _MAX_IMAGE_PX, _resize_image_bytes, _run_cv_phase1, _check_ultralytics,
    _run_cv_phase2, _segs_to_dicts, _filter_degenerate_segments,
    _snap_segments_to_symbols, _run_full_cv,
    _cv_shared_header, _cv_seg_touches, _build_symbol_summary,
    _build_connection_summary, _call_llm_verification, _chain_pixel_segments,
    _format_proposed_graph, _call_llm_connections,
    run_extraction, _KIND_TO_CATEGORY, _merge, _finish,
    build_parser, main,
)

if __name__ == '__main__':
    main()
