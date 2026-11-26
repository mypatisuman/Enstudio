"""
helpers/cv_detection_helper.py — 3-stage CV detection pipeline coordinator
(YOLO symbols, then OCR text + UNet lines in parallel).

Extracted from main.py (Phase 9): _run_cv_detection(), moved verbatim.
`_DETECTION_AVAILABLE` and the three detection functions are pulled in via
a function-local `import main as _m` — the same lazy-import pattern used
by the Phase 8 controllers and bootstrap/cv_bootstrap.py — since these come
from main.py's top-level try/except around `from services.detection_service
import ...` (graceful no-op when the CV weights/services aren't
importable), not from this helper directly.
"""
from __future__ import annotations


def _run_cv_detection(image_bytes: bytes, base_name: str,
                      detection_dir: str, diagram_type: str = None) -> dict:
    """
    Run the 3-stage CV detection pipeline and return combined results.

    Phase 1 (serial):   YOLO symbol detection
    Phase 2 (parallel): OCR text detection  +  UNet line detection

    Results are saved as JSON/PNG files in detection_dir.
    Returns dict with keys: symbols, texts, lines, available.
    """
    import main as _m
    _DETECTION_AVAILABLE = _m._DETECTION_AVAILABLE
    if not _DETECTION_AVAILABLE:
        return {'available': False, 'symbols': [], 'texts': [], 'lines': []}

    process_detect_symbols = _m.process_detect_symbols
    detect_text_from_bytes = _m.detect_text_from_bytes
    detect_lines_from_bytes = _m.detect_lines_from_bytes

    from concurrent.futures import ThreadPoolExecutor

    print(f'[detection] Phase 1: YOLO symbol detection ({base_name})')
    symbol_result = process_detect_symbols(
        image_bytes,
        original_filename=base_name,
        diagram_type=diagram_type,
        output_dir=detection_dir,
    )
    symbol_detections = symbol_result.get('detections', [])
    if symbol_result.get('error'):
        print(f'[detection] YOLO warning: {symbol_result["error"]}')
    print(f'[detection] Phase 1 done: {len(symbol_detections)} symbols')

    print(f'[detection] Phase 2: OCR + UNet in parallel')
    with ThreadPoolExecutor(max_workers=2) as pool:
        text_future = pool.submit(detect_text_from_bytes, image_bytes, symbol_detections)
        line_future = pool.submit(
            detect_lines_from_bytes, image_bytes, symbol_detections,
            detection_dir, base_name,
        )
        text_result = text_future.result()
        line_result = line_future.result()

    if text_result.get('error'):
        print(f'[detection] OCR warning: {text_result["error"]}')
    if line_result.get('error'):
        print(f'[detection] UNet warning: {line_result["error"]}')

    print(
        f'[detection] Phase 2 done: {text_result.get("count", 0)} texts, '
        f'{line_result.get("count", 0)} lines'
    )

    return {
        'available': True,
        'symbols':   symbol_detections,
        'texts':     text_result.get('texts', []),
        'lines':     line_result.get('lines', []),
        'symbol_image': symbol_result.get('image_path', ''),
        'line_image':   line_result.get('image_path', ''),
    }
