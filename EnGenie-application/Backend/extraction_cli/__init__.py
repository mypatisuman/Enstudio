"""
extraction_cli/__init__.py — public API surface for the extraction CLI package.

Phase 11: extract_cli.py (~1900 lines) was decomposed into this package:

    output.py           NDJSON stdout emission + fatal-error helper
    pdf.py               PDF-to-PNG rendering
    image.py             CV detection pipeline (YOLO/OCR/UNet) on image bytes
    llm_verification.py  LLM verification + connection-identification pass
    commands.py           run_extraction() workflow orchestration
    parser.py             argparse setup
    main.py                CLI entry point (parse -> validate -> dispatch)

The root-level `studio/extract_cli.py` remains a real file (not replaced by
a package) because it's spawned directly as a script by the Tauri desktop
sidecar (`python extract_cli.py <hub> <pid> <pdf>`, per CLAUDE.md) — turning
it into a directory would break that literal invocation. It is now a thin
compatibility shim that imports from this package; `from extract_cli import
main` and `from extract_cli import _snap_segments_to_symbols` (used by
tests/test_snap_segments.py) both keep working unchanged.

Re-exports the complete original attribute surface (not just names with
confirmed external callers) so no caller this audit missed breaks.
"""
from __future__ import annotations

from .output import emit, die
from .pdf import _render_pdf_to_png, _pdf_page_count
from .image import (
    _MAX_IMAGE_PX, _resize_image_bytes, _run_cv_phase1, _check_ultralytics,
    _run_cv_phase2, _segs_to_dicts, _filter_degenerate_segments,
    _snap_segments_to_symbols, _run_full_cv,
)
from .llm_verification import (
    _cv_shared_header, _cv_seg_touches, _build_symbol_summary,
    _build_connection_summary, _call_llm_verification, _chain_pixel_segments,
    _format_proposed_graph, _call_llm_connections,
    LlmStageError, _parse_llm_json, _with_retries,
)
from .status import ExtractionStatus, Reason
from .commands import (
    run_extraction, _KIND_TO_CATEGORY, _merge, _finish,
    _extract_one_page, _page_prefix, _scope_ids, _derive_studio_tables,
)
from .parser import build_parser
from .main import main

__all__ = [
    'emit', 'die',
    '_render_pdf_to_png', '_pdf_page_count',
    '_MAX_IMAGE_PX', '_resize_image_bytes', '_run_cv_phase1', '_check_ultralytics',
    '_run_cv_phase2', '_segs_to_dicts', '_filter_degenerate_segments',
    '_snap_segments_to_symbols', '_run_full_cv',
    '_cv_shared_header', '_cv_seg_touches', '_build_symbol_summary',
    '_build_connection_summary', '_call_llm_verification', '_chain_pixel_segments',
    '_format_proposed_graph', '_call_llm_connections',
    'LlmStageError', '_parse_llm_json', '_with_retries',
    'ExtractionStatus', 'Reason',
    'run_extraction', '_KIND_TO_CATEGORY', '_merge', '_finish',
    '_extract_one_page', '_page_prefix', '_scope_ids', '_derive_studio_tables',
    'build_parser', 'main',
]
