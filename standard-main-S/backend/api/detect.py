"""Detection pipeline router — /api/upload, /api/detect-all, /api/detection-files."""
import os
import re
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse, FileResponse

logger = logging.getLogger(__name__)

router = APIRouter(tags=['detection'])

# Shared executor for Phase 2 parallel tasks (OCR + line detection)
_executor = ThreadPoolExecutor(max_workers=4)

# Output directory — relative to main.py location; overridden by app startup
_DETECTIONS_DIR = Path(__file__).parent.parent / 'detections'


def _detections_dir_for(pid: str) -> Path:
    d = _DETECTIONS_DIR / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


# ---------------------------------------------------------------------------
# POST /api/projects/{pid}/upload  — save image/PDF for a project
# ---------------------------------------------------------------------------

@router.post('/api/projects/{pid}/upload')
async def upload_image(pid: str, file: UploadFile = File(...)):
    """Save an uploaded image or PDF to the project's source_docs folder."""
    from pathlib import Path as _P

    image_bytes = await file.read()
    filename    = file.filename or 'source.png'
    safe_name   = re.sub(r'[^\w\-_. ]', '_', filename).strip() or 'source.png'

    # Resolve projects dir from main module (injected at startup)
    try:
        import main as _m
        projects_dir = _m.PROJECTS_DIR
    except Exception:
        projects_dir = _P(__file__).parent.parent.parent / 'EngineeringHub' / 'EngineeringHub' / 'projects'

    source_dir = _P(projects_dir) / pid / 'source_docs'
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / safe_name).write_bytes(image_bytes)

    return {
        'filename': safe_name,
        'size':     len(image_bytes),
        'pid':      pid,
    }


# ---------------------------------------------------------------------------
# POST /api/projects/{pid}/detect  — full detection pipeline
# ---------------------------------------------------------------------------

@router.post('/api/projects/{pid}/detect')
async def detect_all(pid: str, file: UploadFile = File(...)):
    """Run the full detection pipeline on an uploaded image:

    Phase 1 (serial):   YOLO symbol detection
    Phase 2 (parallel): OCR text detection  +  UNet line detection

    Returns combined results: {symbols, texts, lines}.
    """
    import asyncio
    # Resolved through the shared router rather than hardwired to the CV
    # services. This endpoint used to always run YOLO/OCR/U-Net even when the
    # rest of the app was configured for the vision-LLM engine, so the same
    # drawing gave different answers here than through the upload route.
    from services.detection_router import resolve_backend
    _backend = resolve_backend()
    process_detect_symbols = _backend.detect_symbols
    detect_text_from_bytes = _backend.detect_text
    detect_lines_from_bytes = _backend.detect_lines
    logger.info("[detect/%s] detection engine: %s (%s)", pid,
                _backend.engine, _backend.reason)

    image_bytes = await file.read()
    filename    = file.filename or f'image_{int(time.time())}.png'
    safe_name   = re.sub(r'[^\w\-_. ]', '_', filename).strip()
    base_name   = os.path.splitext(safe_name)[0]

    output_dir = str(_detections_dir_for(pid))

    # ── Phase 1: YOLO symbol detection (serial, must finish before Phase 2) ──
    logger.info("[detect/%s] Phase 1: YOLO symbol detection", pid)
    symbol_result = process_detect_symbols(
        image_bytes,
        original_filename=safe_name,
        output_dir=output_dir,
    )
    if symbol_result.get('error'):
        # Soft failure — continue with empty boxes so OCR + lines still run
        logger.warning("[detect/%s] YOLO failed: %s", pid, symbol_result['error'])

    symbol_detections = symbol_result.get('detections', [])
    logger.info("[detect/%s] Phase 1 done: %d symbols", pid, len(symbol_detections))

    # ── Phase 2: OCR + UNet in parallel via ThreadPoolExecutor ───────────────
    logger.info("[detect/%s] Phase 2: OCR + UNet in parallel", pid)
    loop = asyncio.get_event_loop()

    text_future = loop.run_in_executor(
        _executor,
        detect_text_from_bytes,
        image_bytes,
        symbol_detections,
    )
    line_future = loop.run_in_executor(
        _executor,
        detect_lines_from_bytes,
        image_bytes,
        symbol_detections,
        output_dir,
        base_name,
    )

    text_result, line_result = await asyncio.gather(
        text_future, line_future, return_exceptions=True
    )

    if isinstance(text_result, Exception):
        logger.exception("[detect/%s] OCR phase failed: %s", pid, text_result)
        text_result = {'error': str(text_result), 'texts': []}

    if isinstance(line_result, Exception):
        logger.exception("[detect/%s] UNet phase failed: %s", pid, line_result)
        line_result = {'error': str(line_result), 'lines': []}

    logger.info(
        "[detect/%s] Phase 2 done: %d texts, %d lines",
        pid,
        len(text_result.get('texts', [])),
        len(line_result.get('lines', [])),
    )

    return {
        'pid':     pid,
        'file':    safe_name,
        'symbols': {
            'detections': symbol_detections,
            'count':      len(symbol_detections),
            'image_path': symbol_result.get('image_path', ''),
            'json_path':  symbol_result.get('json_path', ''),
            'error':      symbol_result.get('error'),
        },
        'texts': {
            'texts': text_result.get('texts', []),
            'count': text_result.get('count', 0),
            'error': text_result.get('error'),
        },
        'lines': {
            'lines':      line_result.get('lines', []),
            'count':      line_result.get('count', 0),
            'image_path': line_result.get('image_path', ''),
            'json_path':  line_result.get('json_path', ''),
            'error':      line_result.get('error'),
        },
    }


# ---------------------------------------------------------------------------
# GET /api/projects/{pid}/detection-files  — list saved detection outputs
# ---------------------------------------------------------------------------

@router.get('/api/projects/{pid}/detection-files')
def list_detection_files(pid: str):
    """List all saved detection JSON files for a project."""
    det_dir = _detections_dir_for(pid)
    files = []
    for p in sorted(det_dir.iterdir()):
        if p.suffix == '.json':
            files.append({
                'name':     p.name,
                'path':     str(p),
                'size':     p.stat().st_size,
                'modified': p.stat().st_mtime,
            })
    return {'pid': pid, 'files': files}


# ---------------------------------------------------------------------------
# GET /api/projects/{pid}/detection-files/{filename}  — serve a detection file
# ---------------------------------------------------------------------------

@router.get('/api/projects/{pid}/detection-files/{filename}')
def get_detection_file(pid: str, filename: str):
    det_dir = _detections_dir_for(pid)
    path = det_dir / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail=f'Detection file not found: {filename}')
    return FileResponse(str(path), media_type='application/json')
