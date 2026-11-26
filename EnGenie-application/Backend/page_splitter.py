"""
page_splitter.py — Split a multi-page P&ID PDF into individual page images.
"""
from __future__ import annotations

import os
from pathlib import Path


def split_pdf_to_pages(pdf_path: str, output_dir: str, dpi: int = 200) -> list[dict]:
    """
    Split a multi-page P&ID PDF into individual page PNGs.

    Args:
        pdf_path:   path to the source PDF
        output_dir: directory to write page_1.png, page_2.png, ...
        dpi:        render resolution (default 200 — captures all P&ID detail within API limits)

    Returns:
        List of dicts, one per page:
        [{"page": 1, "image_path": "/abs/path/page_1.png",
          "width": 2400, "height": 1700}, ...]
    """
    import fitz  # pymupdf

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    scale = dpi / 72.0          # fitz default unit is 72 dpi
    matrix = fitz.Matrix(scale, scale)

    doc = fitz.open(pdf_path)
    results: list[dict] = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        pix  = page.get_pixmap(matrix=matrix, alpha=False)

        img_path = out / f"page_{page_num + 1}.png"
        pix.save(str(img_path))

        results.append({
            "page":       page_num + 1,
            "image_path": str(img_path.resolve()),
            "width":      pix.width,
            "height":     pix.height,
        })

    doc.close()
    return results


def pdf_to_png(pdf_path: str, output_dir: str, dpi: int = 200) -> dict:
    """
    Convert the first page of a single-drawing PDF to a PNG.

    The PNG is named after the PDF stem so multiple PDFs in one cache/pages
    directory don't overwrite each other (unlike split_pdf_to_pages which
    always writes page_1.png).

    Returns:
        {"image_path": str, "width": int, "height": int, "pdf_name": str}
    """
    import fitz

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    pdf = Path(pdf_path)
    safe_stem = pdf.stem.replace(" ", "_")
    img_path  = out / f"{safe_stem}.png"

    scale  = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    doc    = fitz.open(str(pdf))
    page   = doc[0]
    pix    = page.get_pixmap(matrix=matrix, alpha=False)
    pix.save(str(img_path))
    doc.close()

    return {
        "image_path": str(img_path.resolve()),
        "width":      pix.width,
        "height":     pix.height,
        "pdf_name":   pdf.name,
    }
