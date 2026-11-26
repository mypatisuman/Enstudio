"""
extraction_cli/pdf.py -- PDF page rendering for the CV pipeline.

Phase 1: this module rendered page 1 only (`doc[0]`), so every page after the
first of a multi-page drawing set was silently dropped -- the run still
reported success. It now exposes the page count and renders any requested
page; run_extraction() iterates.
"""
from __future__ import annotations

from .image import _MAX_IMAGE_PX
from .output import emit, die


def _pdf_page_count(pdf_bytes: bytes) -> int:
    """Number of pages in the PDF. 0 if it cannot be opened as one."""
    try:
        import fitz
    except ImportError:
        die("PyMuPDF (fitz) not installed — required for PDF processing. "
            "Run: pip install pymupdf")
    try:
        doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    except Exception:
        return 0
    try:
        return doc.page_count
    finally:
        doc.close()


def _render_pdf_to_png(pdf_bytes: bytes, page_index: int = 0) -> tuple[bytes, int, int]:
    """Render one page of a PDF to PNG bytes, capped at _MAX_IMAGE_PX.

    page_index is 0-based. Returns (png_bytes, width, height) -- the caller
    needs the raster dimensions because every downstream coordinate is
    normalised against THIS page's own raster, which keeps each page
    spatially independent (page 2 does not inherit page 1's scale).

    The default page_index=0 preserves the original single-page call shape;
    only the return type widened (was bare bytes) and every call site in this
    package was updated with it.
    """
    try:
        import fitz
    except ImportError:
        die("PyMuPDF (fitz) not installed — required for PDF processing. "
            "Run: pip install pymupdf")

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    n_pages = doc.page_count          # read BEFORE close(); the property raises after
    if page_index < 0 or page_index >= n_pages:
        doc.close()
        die(f"Page index {page_index} out of range (PDF has {n_pages} pages)")
    page = doc[page_index]

    # Compute scale so the longest side hits _MAX_IMAGE_PX exactly.
    # Per-page: a mixed-size document (A1 sheet + A4 index page) gets each
    # page scaled on its own dimensions rather than the first page's.
    rect  = page.rect
    scale = _MAX_IMAGE_PX / max(rect.width, rect.height)
    # Never upscale below 1.5x native (keeps symbols readable for YOLO/UNet)
    scale = max(scale, 1.5)

    pix       = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    png_bytes = pix.tobytes('png')
    width, height = pix.width, pix.height
    doc.close()

    emit({"stage": "pdf_render", "status": "size",
          "page": page_index + 1,
          "width": width, "height": height, "scale": round(scale, 3)})
    return png_bytes, width, height
