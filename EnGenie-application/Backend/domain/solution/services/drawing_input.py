"""Input quality: the uploaded drawing prepared, checked and gated before the
(expensive) vision passes run.

    load_page   a PDF page rendered at a resolution set for reading (vector PDFs
                stay crisp; the general PDF renderer caps the long side at 4096 px,
                where 5100 px sheets read best), an image with its camera rotation
                applied and transparency flattened onto white
    normalise   grey levels, white background (a negative scan is inverted), the
                contrast stretched when the scan is washed out, and the size set so
                tags fill enough pixels inside a reading tile
    probe       one cheap vision call on the whole page: is it a P&ID, does it need
                turning upright, is the text legible
    gate        "block" an upload that is not a P&ID or cannot be read (nothing is
                spent on it), "warn" for a borderline one

Plain image operations only (resize, contrast, rotate): no pixel analysis, no
local model - the drawing is still read only by the vision LLM.
"""
from __future__ import annotations

import io
import json
import logging
import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

#: Long side of the page the reading tiles are cut from. The benchmark drawings are
#: 5100 px wide; below ~4800 px small bubble text drops under ~20 px per character.
MIN_LONG_SIDE = int(os.getenv("BROWNFIELD_MIN_LONG_SIDE", "4800"))
MAX_LONG_SIDE = int(os.getenv("BROWNFIELD_MAX_LONG_SIDE", "8000"))
PDF_LONG_SIDE = int(os.getenv("BROWNFIELD_PDF_LONG_SIDE", "6000"))
MAX_UPSCALE = 3.0                 # beyond this the scan is simply too small to read reliably
LOW_CONTRAST_SPAN = 160           # paper-to-ink grey difference below which contrast is stretched
INK_MARGIN = 30                   # a pixel this much darker than the paper counts as ink
PROBE_MODEL = os.getenv("BROWNFIELD_PROBE_MODEL", "").strip()
GATE_MODE = os.getenv("BROWNFIELD_QUALITY_GATE", "block").strip().lower()   # block | warn | off


def load_page(f_bytes: bytes, mime: str | None) -> tuple["Image.Image", list[str], dict]:
    """The first page as a PIL image (mode kept), the warnings, and what was done."""
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = None
    warnings: list[str] = []
    report: dict = {"source": "image"}
    if (mime or "").endswith("pdf") or f_bytes[:4] == b"%PDF":
        import fitz
        doc = fitz.open(stream=f_bytes, filetype="pdf")
        try:
            if doc.page_count > 1:
                warnings.append(f"PDF has {doc.page_count} pages; only page 1 was digitised.")
            page = doc[0]
            scale = PDF_LONG_SIDE / max(page.rect.width, page.rect.height)
            pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            img = Image.open(io.BytesIO(pix.tobytes("png")))
            img.load()
        finally:
            doc.close()
        report.update(source="pdf", pdf_scale=round(scale, 3))
        return img, warnings, report
    img = Image.open(io.BytesIO(f_bytes))
    img.load()
    turned = ImageOps.exif_transpose(img)            # a phone photo's stored rotation
    if turned is not img:
        report["exif_rotated"] = True
        img = turned
    return img, warnings, report


def normalise(img, report: dict | None = None) -> tuple["Image.Image", dict]:
    """Grey, white background, readable contrast, reading resolution."""
    from PIL import Image, ImageOps
    report = dict(report or {})
    issues: list[str] = []
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        white = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(white, img)
    img = img.convert("L")
    report["original_px"] = list(img.size)

    def percentile(hist: list[int], q: float) -> int:
        total, acc = sum(hist) or 1, 0
        for v, n in enumerate(hist):
            acc += n
            if acc >= q * total:
                return v
        return 255

    # a P&ID is >99% paper: compare the paper (median) with the ink (the darkest
    # 0.2%), not the 1st-99th percentiles, which are both paper on a clean sheet
    hist = img.histogram()
    if percentile(hist, 0.5) < 110:                    # a negative: light lines on dark paper
        img = ImageOps.invert(img)
        report["inverted"] = True
        issues.append("negative scan inverted to dark lines on white")
        hist = img.histogram()
    paper = percentile(hist, 0.5)
    # the ink: the typical grey of the pixels clearly darker than the paper (none: a
    # blank or near-blank page, nothing to stretch)
    dark = hist[:max(0, paper - INK_MARGIN)]
    ink = percentile(dark, 0.5) if sum(dark) else paper
    report["paper_level"], report["ink_level"] = paper, ink
    if sum(dark) and paper - ink < LOW_CONTRAST_SPAN:
        span = max(1, paper - ink)
        img = img.point([max(0, min(255, round((v - ink) * 255 / span))) for v in range(256)])
        report["contrast_stretched"] = True
        issues.append(f"faint scan (ink {ink} on paper {paper}): contrast stretched")

    long_side = max(img.size)
    scale = 1.0
    if long_side < MIN_LONG_SIDE:
        scale = min(MAX_UPSCALE, MIN_LONG_SIDE / long_side)
        if MIN_LONG_SIDE / long_side > MAX_UPSCALE:
            issues.append(f"low resolution ({long_side} px on the long side): small text may not be readable")
            report["too_small"] = True
    elif long_side > MAX_LONG_SIDE:
        scale = MAX_LONG_SIDE / long_side
    if abs(scale - 1.0) > 0.01:
        img = img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))),
                         Image.Resampling.LANCZOS)
    report["scale"] = round(scale, 3)
    report["final_px"] = list(img.size)
    report["issues"] = issues
    return img, report


_PROBE_PROMPT = """You are checking an uploaded drawing before it is digitised.
Answer about the WHOLE image:
1. is_pid: is it a piping and instrumentation diagram (P&ID) or a similar process / instrument diagram?
2. rotation: by how many degrees CLOCKWISE must the image be turned so that most of its text reads
   upright, left to right? One of 0, 90, 180, 270.
3. legibility: can the small text (instrument tags in bubbles, line numbers) be read?
   "good" = clearly, "fair" = with effort or partly, "poor" = mostly not.
4. reason: one short sentence.
Respond with JSON only: {"is_pid": true, "rotation": 0, "legibility": "good", "reason": "..."}"""


def _probe_call(png: bytes) -> str:
    """Module-level for testability."""
    from domain.solution.services.brownfield_vision_service import _vision_call
    kw = {"model": PROBE_MODEL} if PROBE_MODEL else {}
    return _vision_call(_PROBE_PROMPT, png, 200, **kw)


def probe(img) -> dict | None:
    """The vision model's verdict on the whole page, or None when it cannot be had."""
    from domain.solution.services.brownfield_vision_service import _parse_json
    small = img.copy()
    small.thumbnail((1600, 1600))
    buf = io.BytesIO()
    small.save(buf, "PNG", optimize=True)
    try:
        data = _parse_json(_probe_call(buf.getvalue()))
    except Exception as exc:
        logger.info("[drawing_input] probe unavailable: %s", exc)
        return None
    if not isinstance(data, dict) or "is_pid" not in data:
        return None
    rotation = data.get("rotation")
    try:
        rotation = int(rotation) % 360
    except (TypeError, ValueError):
        rotation = 0
    return {"is_pid": bool(data.get("is_pid")), "rotation": rotation if rotation in (0, 90, 180, 270) else 0,
            "legibility": str(data.get("legibility") or "good").lower(), "reason": str(data.get("reason") or "")[:200]}


def gate(report: dict, verdict: dict | None, mode: str | None = None) -> tuple[str, str] | None:
    """("block" | "warn", message), or None when the drawing is fit to read."""
    mode = (mode or GATE_MODE)
    if mode == "off":
        return None
    problems, severe = [], False
    if verdict is not None:
        if not verdict["is_pid"]:
            problems.append(f"this does not look like a P&ID ({verdict['reason'] or 'no diagram recognised'})")
            severe = True
        if verdict["legibility"] == "poor":
            problems.append(f"the text cannot be read reliably ({verdict['reason'] or 'illegible'})")
            severe = True
        elif verdict["legibility"] == "fair":
            problems.append("parts of the text are hard to read; expect more items in the review queue")
    if report.get("too_small"):
        problems.append(f"the image is small ({max(report.get('original_px') or [0])} px on its long side)")
    if not problems:
        return None
    level = "block" if severe and mode == "block" else "warn"
    return level, "; ".join(problems)


def prepare(f_bytes: bytes, mime: str | None, *, use_probe: bool = True) -> dict:
    """Everything above, in order. Returns {"img", "warnings", "report", "verdict", "gate", "rotated"}."""
    from PIL import Image
    img, warnings, report = load_page(f_bytes, mime)
    img, report = normalise(img, report)
    verdict = probe(img) if use_probe else None
    rotated = 0
    if verdict and verdict["rotation"]:
        rotated = verdict["rotation"]
        img = img.rotate(-rotated, expand=True, fillcolor=255, resample=Image.Resampling.BICUBIC)
        report["rotated"] = rotated
        warnings.append(f"The drawing was turned {rotated} degrees clockwise to read it upright.")
    verdict_gate = gate(report, verdict)
    warnings += [f"Input: {i}." for i in report.get("issues") or []]
    if verdict_gate and verdict_gate[0] == "warn":
        warnings.append(f"Input quality: {verdict_gate[1]}.")
    report["verdict"] = verdict
    return {"img": img, "warnings": warnings, "report": report, "verdict": verdict, "gate": verdict_gate,
            "rotated": rotated}


def summary(report: dict) -> str:
    return json.dumps({k: report.get(k) for k in ("source", "original_px", "final_px", "scale", "inverted",
                                                  "contrast_stretched", "rotated", "issues")})
