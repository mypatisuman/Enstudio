"""
Brownfield Vision Service — visual analysis and digital P&ID graph reconstruction.

Powered by a DeepInfra-hosted multimodal vision model (Qwen/Qwen3-VL-30B-A3B-Instruct
by default; override with BROWNFIELD_VISION_MODEL / DEEPINFRA_MODEL_SMART).

Responsibilities:
1. resolve_uploaded_drawing: locates the project's uploaded P&ID (sources table,
   EngineeringHub project folder, extraction temp folder). Demo fixtures are only
   used when explicitly enabled.
2. analyze_uploaded_pid: tiled, multi-pass visual reading of the drawing:
     pass 1  read      — every tile is read independently for printed tags
     pass 2  verify    — each candidate tag is re-read in a small crop around it
     pass 3  connect   — per tile, which of the KNOWN tags are joined by a line
     pass 4  overview  — downscaled full sheet: title + systems/subsystems,
                          constrained to the known tag list
   Loops are derived deterministically from ISA numbering.
3. rebuild_digital_pid: persists an analysis as the project's digital P&ID graph
   (SQLite studio.db + MongoDB PIDGraphRepository) with origin='extracted'.

Why tiled: a whole E-size sheet sent as one image is downscaled by the model
server until valve and check-valve tags are unreadable, and asking for the
whole plant in one response either truncates at the token cap or degenerates
into a repetition loop. On pid2.png the single-shot call found 30 of 74 tags;
eight tiles read 69 of 73 printed tags in 16 s.

Nothing in this module invents plant content: if the model cannot be reached,
the caller gets an ERROR and nothing is written.
"""

from __future__ import annotations

import base64
import hashlib
import io
import itertools
import json
import logging
import math
import mimetypes
import os
import re
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable


logger = logging.getLogger(__name__)

# Primary vision model for P&ID extraction (informational; the provider's
# "smart" tier decides what is actually called).
VISION_MODEL = os.getenv("BROWNFIELD_VISION_MODEL") or os.getenv(
    "DEEPINFRA_MODEL_SMART", "Qwen/Qwen3-VL-30B-A3B-Instruct")

CANVAS_WIDTH = 1000.0          # output frame: x in 0..1000, y keeps the sheet aspect
#: Prepare, check and gate the upload before reading it (domain/solution/services/drawing_input.py)
INPUT_PREP = os.getenv("BROWNFIELD_INPUT_PREP", "1").strip().lower() not in ("0", "false", "no", "off")
TILE_TARGET_PX = 1500          # tile side the model reads reliably at full detail
# reading grids (tile side in px); their union is read. The first two also trace connections.
TILE_GRIDS = tuple(int(v) for v in os.getenv("BROWNFIELD_TILE_GRIDS", f"{TILE_TARGET_PX},1000").split(",") if v.strip())
TILE_OVERLAP = 0.12            # fraction of a tile shared with each neighbour
VERIFY_CROP_FRAC = 0.07        # verify crop half-size, as a fraction of sheet width
MERGE_DIST_FRAC = 0.03         # same tag closer than this (of width) = same object
MAX_WORKERS = int(os.getenv("BROWNFIELD_VISION_WORKERS", "10"))
# Model that traces connections. On pid2 (same tags, same prompt) the 235B
# model scored connection F1 64% at 74% precision vs 52% / 54% for the 30B
# reading model, in half the time. It was NOT better at reading tags (it
# split repeated interlock bubbles and read heat-trace labels as equipment),
# so tag reading stays on the default model. Set to "" to use one model.
CONNECT_CONSENSUS = os.getenv("BROWNFIELD_CONNECT_CONSENSUS", "1").strip().lower() not in ("0", "false", "no")
CONNECT_MODEL = os.getenv("BROWNFIELD_CONNECT_MODEL", "Qwen/Qwen3-VL-235B-A22B-Instruct").strip()
# A second model traces the connections too: a link either model found is kept, and
# one only ONE of them found goes to the engineer's review queue. Benchmark (pid13 /
# pid15, same tags): Gemini 3.1 Pro 82.7 / 77.9 F1, Claude Sonnet 5.5 75.0 / 78.6;
# links both reported were 91% / 100% right. "" = one model.
CONNECT_SECOND_MODEL = os.getenv("BROWNFIELD_CONNECT_SECOND_MODEL", "").strip()
# One model call may take this long before it is abandoned (the shared
# client's default is 600 s, retried up to 3 more times by the provider).
CALL_TIMEOUT_S = float(os.getenv("BROWNFIELD_VISION_CALL_TIMEOUT", "120"))
LONG_CALL_TIMEOUT_S = float(os.getenv("BROWNFIELD_VISION_LONG_CALL_TIMEOUT", "300"))   # overview
# A whole pass is abandoned after this; unfinished calls count as failed.
# Box-format answers are 2-3x longer than bare x, y; at 240 s dense tiles of
# pid12 (13 of them) and pid13 were abandoned mid-answer.
PASS_TIMEOUT_S = float(os.getenv("BROWNFIELD_VISION_PASS_TIMEOUT", "600"))

_BACKEND_DIR = Path(__file__).resolve().parents[3]
_CACHE_DIR = _BACKEND_DIR / "data" / "brownfield_vision"

# ═══════════════════════════════════════════════════════════════════════════
# Prompts — deliberately free of example plant tags: the old prompt's
# "C-101, V-102, P-101A" examples were copied into results as real equipment.
# ═══════════════════════════════════════════════════════════════════════════

_READ_PROMPT = """You are reading ONE TILE cut from a larger P&ID drawing.
Report every equipment, instrument, valve and header TAG that is actually printed inside this tile.

Rules:
- Instrument bubbles print the function letters above the loop number: join them as LETTERS-NUMBER.
- Valve and equipment tags are printed next to the symbol: report them exactly as printed.
- Off-page connectors / battery-limit headers (a name next to a flag-shaped box): kind "header",
  tag = the printed header name.
- Descriptive words that are not tags (service names, valve-type or meter-type annotations)
  are NOT tags. Never combine such a word with a nearby number to make a tag.
- Skip the title block, notes, revision table and the border grid numbers/letters.
- Never guess or invent. If a tag is not clearly readable, leave it out.
- List each printed tag once.

ALSO locate, as separate entries, the short annotations printed next to symbols (a valve's fail
position, a meter or valve type, a filter rating, a service word) with kind "note", and pipe line
numbers / sizes (fluid code, number, size and pipe spec, or a size change) with kind "line".
Report only annotations you can read in THIS tile, word for word; do not add any that are not printed.

kind is one of: vessel, tank, column, pump, compressor, heat_exchanger, mixer, filter, reactor,
control_valve, regulator, hand_valve, check_valve, relief_valve, indicator, transmitter,
controller, element, header, note, line, other

Output a JSON list. Each entry: "bbox_2d": [x1, y1, x2, y2] of the printed tag text, "label": the tag
as printed, "kind": its kind.
Respond with JSON only: [{"bbox_2d": [x1, y1, x2, y2], "label": "TAG", "kind": "kind"}]"""

_VERIFY_PROMPT = """This is a small crop of a P&ID drawing. Transcribe every tag or label printed
in it, exactly as printed. Instrument bubbles print letters above a number: write them as LETTERS-NUMBER.
Do not guess text you cannot read. Respond with JSON only: {"texts": ["...", "..."]}"""

# Connections are asked for as ordered RUNS (how an engineer reads a P&ID)
# rather than as pairs; consecutive items in a run are connected.
_CONNECT_PROMPT = """This is ONE TILE of a larger P&ID drawing. These tagged items were read in it
(label position as x,y in 0-1000 relative to this tile):
{tags}

Trace every pipe run and every instrument signal line in this tile. For each run, list the tagged
items it passes through IN ORDER from one end to the other. Where a run branches, start a new run at
the branch point, beginning with the last item before the branch. Skip runs that pass no listed item.
Use ONLY tags from the list, spelled exactly as given.

Respond with compact JSON only: {{"runs": [["TAG", "TAG", "TAG"], ["TAG", "TAG"]]}}"""

_HEADER_PROMPT = """This is a horizontal strip of a P&ID drawing containing the header line whose flag is
labelled {hdr} (flag near x={hx}, y={hy} in 0-1000 relative to this strip). Tagged items in the strip
(label positions, same coordinates):
{tags}

Follow the header line from the {hdr} flag along its whole length. List:
  "on_line": the FIRST tagged item on every branch that leaves the header line, and any tagged item
             sitting directly on the header line itself, in order along the line;
  "other_end": the tag of the flag/item at the far end of the header line, if it is one of the listed tags.
Use ONLY tags from the list, spelled exactly as given. Do not list items on other lines.

Respond with compact JSON only: {{"on_line": ["TAG"], "other_end": "TAG or null"}}"""

_OVERVIEW_PROMPT = """This is a complete P&ID drawing. These tags were read from it:
{tags}

1. "drawing_title": the drawing's title or service.
2. "system": the plant system this drawing shows.
3. "subsystems": split the drawing into its functional subsystems the way an engineer would - typically
   one per supply station / train / manifold, plus headers and shared downstream equipment (usually
   4-10 subsystems). List each subsystem's tags. Every tag belongs to exactly one subsystem.
4. "equipment": for each of these equipment tags - {eq} - a short description of what it is, using the
   words printed in its data block on the drawing when there is one; otherwise describe the symbol as drawn.
Use ONLY tags from the lists above.

Respond with compact JSON only:
{{"drawing_title": "...", "system": "...", "subsystems": [["name", ["TAG", "TAG"]]], "equipment": [["TAG", "description"]]}}"""

# ═══════════════════════════════════════════════════════════════════════════
# Request detection
# ═══════════════════════════════════════════════════════════════════════════

_REBUILD_VERB = re.compile(
    r"(?i)\b(analy[sz]\w*|digiti[sz]\w*|re-?build\w*|reconstruct\w*|convert\w*|extract\w*|"
    r"scan\w*|transcrib\w*|import\w*|read|visual\s+inspection)\b")
_REBUILD_OBJECT = re.compile(
    r"(?i)(\bdrawing\w*|\bp&id\w*|\bp&ids\b|\bpids?\b|\bscan\w*|\bimage\w*|\bupload\w*|"
    r"\bdiagram\w*|\bsheet\w*)")
_REBUILD_PHRASE = re.compile(r"(?i)\b(build from image|extract and build|drawing analysis)\b")


def is_vision_rebuild_request(message: str) -> bool:
    """True when the message asks to read/digitise an uploaded drawing.

    Needs both an action (analyse, digitise, rebuild, extract...) and an
    object (drawing, P&ID, scan, upload...), so "add a PT to the uploaded
    header" or "convert the loop to cascade" are not mistaken for it.
    """
    msg = message or ""
    if _REBUILD_PHRASE.search(msg):
        return True
    return bool(_REBUILD_VERB.search(msg) and _REBUILD_OBJECT.search(msg))


# ═══════════════════════════════════════════════════════════════════════════
# Locating the drawing
# ═══════════════════════════════════════════════════════════════════════════

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".pdf", ".tif", ".tiff", ".bmp")


def _demo_fixtures_enabled() -> bool:
    return os.getenv("BROWNFIELD_DEMO_FIXTURES", "").strip().lower() in ("1", "true", "yes")


def _fixture_dirs() -> list[Path]:
    return [
        _BACKEND_DIR / "PID-Images" / "PID-Images",
        _BACKEND_DIR.parent.parent / "standard-main-S" / "fixtures" / "pid-images",
    ]


def _file_result(p: Path) -> tuple[Path, bytes, str]:
    mime, _ = mimetypes.guess_type(str(p))
    return p, p.read_bytes(), mime or "image/png"


def _project_dir(pid: str) -> Path | None:
    try:
        from utils.paths import resolve_hub, resolve_projects_dir
        default_hub = _BACKEND_DIR.parent / "EngineeringHub" / "EngineeringHub"
        hub = resolve_hub(default=default_hub, treat_empty_as_unset=True)
        return resolve_projects_dir(hub) / pid
    except Exception as exc:
        logger.debug(f"[VisionService] Hub resolution failed for {pid}: {exc}")
        return None


def resolve_uploaded_drawing(
    pid: str,
    candidate_path: str | None = None
) -> tuple[Path | None, bytes | None, str]:
    """Locate the drawing file uploaded for a project.

    Search order: explicit path, the project's latest `sources` row, the
    EngineeringHub project folder, the extraction temp folder (pid-specific
    names only). A fixture image is used only when its file name IS the
    project id (e.g. project "pid2" -> pid2.png). The old behaviour of handing
    any unknown project the demo drawing pid18.png is available only with
    BROWNFIELD_DEMO_FIXTURES=1, because it made every empty project look like
    it had a drawing to retrofit.

    Returns (file_path, file_bytes, mime_type) or (None, None, '').
    """
    if candidate_path:
        cp = Path(candidate_path)
        if cp.is_file():
            return _file_result(cp)

    proj_dir = _project_dir(pid)

    # 1. Latest source recorded for the project
    try:
        from adapters.db import get_db
        row = get_db().execute(
            "SELECT filename FROM sources WHERE pid=? ORDER BY id DESC LIMIT 1", (pid,)
        ).fetchone()
        if row and row[0]:
            fp = Path(row[0])
            candidates = [fp]
            if not fp.is_absolute() and proj_dir is not None:
                candidates += [proj_dir / fp, proj_dir / "source_docs" / fp]
            for c in candidates:
                if c.is_file() and c.suffix.lower() in _IMAGE_EXTS:
                    return _file_result(c)
    except Exception as exc:
        logger.debug(f"[VisionService] DB source search failed for {pid}: {exc}")

    # 2. EngineeringHub project folder
    if proj_dir is not None and proj_dir.is_dir():
        for folder in (proj_dir, proj_dir / "source_docs"):
            if not folder.is_dir():
                continue
            for p in sorted(folder.iterdir()):
                if p.is_file() and p.suffix.lower() in _IMAGE_EXTS:
                    return _file_result(p)

    # 3. Extraction temp folder (only files that carry this pid in their name)
    temp_dir = Path(tempfile.gettempdir()) / "engenie_extraction"
    if temp_dir.is_dir():
        for p in temp_dir.glob(f"*{pid}*.*"):
            if p.suffix.lower() in (".png", ".jpg", ".jpeg"):
                return _file_result(p)

    # 4. Fixture whose name is exactly the project id
    for fix_dir in _fixture_dirs():
        exact = fix_dir / f"{pid}.png"
        if exact.is_file():
            return _file_result(exact)

    # 5. Demo mode only: loose fixture matching and the pid18 demo drawing
    if _demo_fixtures_enabled():
        for fix_dir in _fixture_dirs():
            if not fix_dir.is_dir():
                continue
            digits = "".join(filter(str.isdigit, pid))
            for name in ([f"pid{digits}.png"] if digits else []) + ["pid18.png"]:
                p = fix_dir / name
                if p.is_file():
                    logger.info(f"[VisionService] DEMO MODE: using fixture {name} for project {pid}")
                    return _file_result(p)

    return None, None, ""


def _ground_truth_enabled(explicit: bool | None) -> bool:
    if explicit is not None:
        return explicit
    return os.getenv("BROWNFIELD_USE_GROUND_TRUTH", "").strip().lower() in ("1", "true", "yes")


def resolve_benchmark_ground_truth(pid: str, drawing_path: Path | None = None) -> dict[str, Any] | None:
    """Return the benchmark ground-truth JSON for a reference drawing, if one exists.

    Used for SCORING. analyze_uploaded_pid only substitutes it for the
    model's reading when explicitly asked (use_ground_truth=True or
    BROWNFIELD_USE_GROUND_TRUTH=1), because doing it silently made reference
    drawings look perfectly digitised no matter what the model could read.
    """
    search_dirs = [
        _BACKEND_DIR / "fixtures" / "ground_truth",
        _BACKEND_DIR.parent.parent / "standard-main-S" / "fixtures" / "ground_truth",
    ]
    candidates: list[str] = []
    if drawing_path:
        stem = drawing_path.stem.lower()
        candidates.append(stem)
    candidates.append(pid.lower())

    for c in candidates:
        for sdir in search_dirs:
            target = sdir / f"{c}.json"
            if target.is_file():
                try:
                    data = json.loads(target.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        data["pid"] = pid
                        if drawing_path:
                            data["drawing_source"] = str(drawing_path)
                        return data
                except Exception as exc:
                    logger.warning(f"[VisionService] Error reading ground truth {target}: {exc}")
    return None


# ═══════════════════════════════════════════════════════════════════════════
# Model call seam (tests replace _vision_call)
# ═══════════════════════════════════════════════════════════════════════════

_provider_lock = __import__("threading").Lock()
_provider = None


def _vision_provider():
    """A DeepInfra provider of its own, whose client gives up after
    CALL_TIMEOUT_S with no client-level retries. The shared provider keeps
    the OpenAI default (600 s, retried), which let one stuck tile hold the
    whole reading for many minutes."""
    global _provider
    with _provider_lock:
        if _provider is None:
            from adapters.llm_factory import get_provider
            shared = get_provider("deepinfra")
            try:
                import copy
                prov = copy.copy(shared)            # same key, models and settings
                prov._client = shared._client.with_options(timeout=CALL_TIMEOUT_S, max_retries=0)
                _provider = prov
            except Exception as exc:
                logger.debug(f"[VisionService] dedicated client unavailable ({exc}); using shared provider")
                _provider = shared
        return _provider


#: Re-read settings for a tile whose plain read came back empty or looping. At
#: greedy decoding the model can loop on its first item until the token cap
#: (pid18: two whole tiles came back as `["1008", ...]` x100 and were lost).
#: DeepInfra's repetition_penalty 1.1 recovered 38 and 14 tags on those tiles;
#: a frequency penalty is the last resort. Neither is used by default: they
#: also suppress legitimately repeated prefixes (HV-..., CK-...).
READ_SAMPLING = {"extra_body": {"repetition_penalty": 1.1}}
RETRY_SAMPLING = {"frequency_penalty": 0.5}

#: The model of each pass ("" = the provider's configured vision model). Any vision
#: model DeepInfra serves works (Qwen-VL, Gemini, Claude); its boxes are converted
#: to the one convention the pipeline uses (see _model_family / _to_norm).
READ_MODEL = os.getenv("BROWNFIELD_READ_MODEL", "").strip()
VERIFY_MODEL = os.getenv("BROWNFIELD_VERIFY_MODEL", "").strip()
SYMBOL_MODEL = os.getenv("BROWNFIELD_SYMBOL_MODEL", "").strip()


def _default_model() -> str:
    try:
        return _vision_provider()._model_name("smart")
    except Exception:
        return VISION_MODEL


def _model_family(model: str | None) -> str:
    """qwen | gemini | claude: how the model writes a box.
        qwen    [x1, y1, x2, y2], 0-1000 of the image
        gemini  [ymin, xmin, ymax, xmax], 0-1000 of the image (its native order)
        claude  [x1, y1, x2, y2] in pixels of the image it was sent
    Measured on one pid15 tile (TE-3004 at 367, 647): Gemini 3.1 Pro answered
    [642, 362 ...], Claude Sonnet 5.5 (550, 971) on the 1500 px tile."""
    m = (model or _default_model() or "").lower()
    if "gemini" in m or "gemma" in m:
        return "gemini"
    if "claude" in m or "anthropic" in m:
        return "claude"
    return "qwen"


#: Extra completion tokens for models that reason before answering. Their hidden
#: reasoning counts against max_tokens: Gemini 3.7 Flash used 1149 reasoning tokens on
#: one pid15 connection tile and was cut off (finish=length) under the 1200 cap.
#: Billing is per token used, so the headroom costs nothing when it is not needed.
THINKING_ALLOWANCE = int(os.getenv("BROWNFIELD_THINKING_ALLOWANCE", "6000"))


def _token_budget(model: str | None, max_tokens: int) -> int:
    m = (model or "").lower()
    thinks = "gemini" in m or "thinking" in m or "-r1" in m
    return max_tokens + THINKING_ALLOWANCE if thinks else max_tokens


def _strip_thinking(text: str) -> str:
    """A reasoning model's <think>...</think> preamble, when it writes one into the reply."""
    if "</think>" in text:
        return text.rsplit("</think>", 1)[1].strip()
    return text


def _to_norm(box, family: str, size: tuple[int, int] | None) -> tuple[float, float, float, float]:
    """A model's box as [x1, y1, x2, y2] on 0-1000 of the image."""
    a, b, c, d = (float(v) for v in box[:4])
    if family == "gemini":
        a, b, c, d = b, a, d, c
    elif family == "claude" and size:
        w, h = size
        a, c = a / max(1, w) * 1000, c / max(1, w) * 1000
        b, d = b / max(1, h) * 1000, d / max(1, h) * 1000
    return a, b, c, d


def _model_kw(model: str) -> dict:
    """{"model": m} only when a pass has its own model (the default call is unchanged)."""
    return {"model": model} if model else {}


def _sampling_for(model: str | None, sampling: dict | None) -> dict | None:
    """Repetition / frequency penalties are Qwen-on-DeepInfra options; other
    models get a plain retry instead."""
    return sampling if _model_family(model) == "qwen" else None


def _vision_call(prompt: str, png_bytes: bytes, max_tokens: int, sampling: dict | None = None,
                 model: str | None = None, timeout: float | None = None) -> str:
    provider = _vision_provider()
    client = getattr(provider, "_client", None)
    if client is not None and timeout:
        client = client.with_options(timeout=timeout)
    if (sampling or model) and client is not None and hasattr(provider, "_model_name"):
        # The provider wrapper can pass neither sampling options nor a model
        # other than its configured tier, so call the OpenAI-compatible client.
        # That bypasses the provider's retry loop, so connection drops ("closed
        # by the remote host") and 429s are retried here with backoff; they
        # used to fail whole tiles.
        from openai import APIConnectionError, APITimeoutError, RateLimitError
        for attempt in range(3):
            try:
                resp = client.chat.completions.create(
                    model=model or provider._model_name("smart"), temperature=0.0,
                    max_tokens=_token_budget(model or provider._model_name("smart"), max_tokens),
                    messages=[{"role": "user", "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {
                            "url": "data:image/png;base64," + base64.b64encode(png_bytes).decode("utf-8")}}]}],
                    **(sampling or {}))
                return _strip_thinking(resp.choices[0].message.content or "")
            except (APIConnectionError, RateLimitError) as exc:
                if attempt == 2 or isinstance(exc, APITimeoutError):
                    raise
                time.sleep(2 ** attempt * (5 if isinstance(exc, RateLimitError) else 1))
    resp = provider.complete_with_image(
        prompt=prompt,
        image_b64=base64.b64encode(png_bytes).decode("utf-8"),
        media_type="image/png",
        max_tokens=max_tokens,
        force_json=True,
        tier="smart",
    )
    return _strip_thinking(resp.text or "")


def _parse_json(raw: str) -> dict:
    from utils.json_utils import extract_json_object
    try:
        data = extract_json_object(raw or "")
        data = data if isinstance(data, dict) else {}
    except Exception:
        data = {}
    if not data.get("items") and '"items"' in (raw or ""):
        # Truncated or looping output: keep every complete compact item.
        items = [[m[0], m[1], int(m[2]), int(m[3])] for m in _COMPACT_ITEM.findall(raw)]
        if items:
            data["items"] = items
    return data


_COMPACT_ITEM = re.compile(r'\[\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*(\d+)\s*,\s*(\d+)\s*\]')


_GROUNDED = re.compile(r'\{[^{}]*?"bbox_2d"\s*:\s*\[([^\]]*)\][^{}]*?\}', re.S)


def _parse_grounded(raw: str, text_key: str = "label", model: str | None = None,
                    size: tuple[int, int] | None = None) -> dict:
    """Qwen-VL grounding output [{"bbox_2d": [x1,y1,x2,y2], "label": ..., "kind": ...}] ->
    {"items": [[label, kind, cx, cy]]}. The model's own 0-1000 box is its real
    position; asked for bare x, y it invented evenly spaced ones (pid11:
    y = 50, 100, 150 ... for headers really at 386, 582, 778). Complete
    entries are salvaged from a cut-off answer; a legacy {"items": ...}
    answer passes through."""
    legacy = _parse_json(raw)
    if legacy.get("items") or legacy.get("symbols"):
        return legacy
    entries = []
    raw = re.sub(r'"box_2d"', '"bbox_2d"', raw or "")      # Gemini's own key name
    m = re.search(r"\[\s*\{.*\}\s*\]", raw or "", re.S)
    if m:
        try:
            entries = json.loads(m.group(0))
        except Exception:
            entries = []
    if not entries:
        for frag in _GROUNDED.finditer(raw or ""):
            try:
                entries.append(json.loads(frag.group(0)))
            except Exception:
                continue
    items = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            continue
        b = e.get("bbox_2d") or e.get("bbox") or e.get("box_2d")
        try:
            x1, y1, x2, y2 = _to_norm(b, _model_family(model), size)
        except Exception:
            continue
        text = e.get(text_key)
        items.append([text, e.get("kind") or "", (x1 + x2) / 2, (y1 + y2) / 2])
    return {"items": items}


def _item_tag(item) -> str:
    if isinstance(item, (list, tuple)) and item:
        return str(item[0]).strip().upper()
    return str((item or {}).get("tag", "")).strip().upper() if isinstance(item, dict) else ""


def _first_per_tag(items: list) -> list:
    seen, out = set(), []
    for i in items:
        t = _item_tag(i)
        if t and t not in seen:
            seen.add(t)
            out.append(i)
    return out


def _looks_degenerate(data: dict) -> bool:
    """No items, or a list that is mostly the same tag repeated."""
    items = data.get("items") or []
    if not items:
        return True
    tags = [str(i[0] if isinstance(i, (list, tuple)) and i else (i or {}).get("tag")) for i in items]
    return len(tags) >= 10 and len(set(tags)) / len(tags) < 0.5


# ═══════════════════════════════════════════════════════════════════════════
# Image handling and tiling
# ═══════════════════════════════════════════════════════════════════════════

def _load_image(f_bytes: bytes, mime: str):
    """Decode the drawing to a grayscale PIL image (renders page 1 of a PDF)."""
    from PIL import Image
    warnings: list[str] = []
    if (mime or "").endswith("pdf") or f_bytes[:4] == b"%PDF":
        from extraction_cli.pdf import _pdf_page_count, _render_pdf_to_png
        pages = _pdf_page_count(f_bytes)
        if pages > 1:
            warnings.append(f"PDF has {pages} pages; only page 1 was digitised.")
        png, _w, _h = _render_pdf_to_png(f_bytes, 0)
        f_bytes = png
    Image.MAX_IMAGE_PIXELS = None
    img = Image.open(io.BytesIO(f_bytes))
    img.load()
    return img.convert("L"), warnings


def _png(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def plan_tiles(width: int, height: int, target: int = TILE_TARGET_PX,
               overlap: float = TILE_OVERLAP) -> list[dict]:
    """Overlapping tile grid. Each tile also carries its CORE rectangle (the
    grid cell without overlap): a reading is kept only by the tile whose core
    contains it, so an item in an overlap strip is not counted twice."""
    cols = max(1, math.ceil(width / target))
    rows = max(1, math.ceil(height / target))
    cw, ch = width / cols, height / rows
    tiles = []
    for r in range(rows):
        for c in range(cols):
            core = (c * cw, r * ch, (c + 1) * cw, (r + 1) * ch)
            box = (max(0, int(core[0] - overlap * cw)), max(0, int(core[1] - overlap * ch)),
                   min(width, int(math.ceil(core[2] + overlap * cw))),
                   min(height, int(math.ceil(core[3] + overlap * ch))))
            tiles.append({"index": len(tiles), "row": r, "col": c, "box": box, "core": core})
    return tiles


def plan_seam_tiles(width: int, height: int, target: int = TILE_TARGET_PX) -> list[dict]:
    """Tiles centred on the seams between the reading tiles, so a line whose
    ends were read in two different tiles is still seen whole once."""
    base = plan_tiles(width, height, target)
    cols = max(t["col"] for t in base) + 1
    rows = max(t["row"] for t in base) + 1
    cw, ch = width / cols, height / rows
    centres = [(c * cw, (r + 0.5) * ch) for r in range(rows) for c in range(1, cols)]
    centres += [((c + 0.5) * cw, r * ch) for r in range(1, rows) for c in range(cols)]
    tiles = []
    for cx, cy in centres:
        box = (max(0, int(cx - cw / 2)), max(0, int(cy - ch / 2)),
               min(width, int(cx + cw / 2)), min(height, int(cy + ch / 2)))
        tiles.append({"index": 1000 + len(tiles), "box": box, "core": box})
    return tiles


# ═══════════════════════════════════════════════════════════════════════════
# Tag normalisation and classification
# ═══════════════════════════════════════════════════════════════════════════

_TAG_RE = re.compile(r"^[A-Z]{1,5}-\d{2,6}[A-Z]?$")
# Template sheets (pid11/pid12) number nothing: "PI XXXX", "V-XXX", "V HPS XXX",
# "R 1-2". Every occurrence is its own symbol.
_PLACEHOLDER_RE = re.compile(r"^[A-Z]{1,5}-(?:[A-Z]{2,4}-)?X{2,6}$|^[A-Z]{1,2}-\d{1,2}-\d{1,2}$")


def is_placeholder(tag: str) -> bool:
    return bool(_PLACEHOLDER_RE.match(tag))
# Pipe line numbers carry a size and/or a piping spec: "H-1001 -1/2 -T9L",
# "CO2-1003-1/2-T3L", "100-P-101-CS", "4\"-P-1001".
_LINE_NUMBER = re.compile(r'\d+\s*/\s*\d+|\d\s*["”]|-\s*T\d+[A-Z]\b|\b\d+-[A-Z]{1,3}-\d+-[A-Z0-9]+\b')
_TAG_IN_TEXT = re.compile(r"\b[A-Z]{1,5}\s?-\s?\d{2,6}[A-Z]?\b")
_HEADER_WORDS = re.compile(r"(?i)\b(header|hdr|supply|return|feed|battery|limit|b/l|off[- ]?page)\b")

# Exact equipment prefixes come first: "HE" (heat exchanger) must not be
# caught by the one-letter-plus-E element rule below.
_PREFIX_KIND: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"^(V|D)$"), "vessel", "Vessel"),
    (re.compile(r"^(TK|T)$"), "tank", "Tank"),
    (re.compile(r"^P$"), "pump", "Pump"),
    (re.compile(r"^(E|HE|HX)$"), "heat_exchanger", "Heat Exchanger"),
    (re.compile(r"^(K|CP)$"), "compressor", "Compressor"),
    (re.compile(r"^(M|MX)$"), "equipment", "Mixer"),
    (re.compile(r"^R$"), "vessel", "Reactor"),
    (re.compile(r"^F$"), "equipment", "Filter"),
    (re.compile(r"^(PSV|PRV|RV|SV)$"), "valve", "Relief Valve"),
    (re.compile(r"^CK$|^NRV$"), "valve", "Check Valve"),
    (re.compile(r"^(HV|XV|BV|GV)$"), "valve", "Hand / Isolation Valve"),
    (re.compile(r"^(BPR|PCV|PRC)$"), "valve", "Pressure Regulator / Control Valve"),
    (re.compile(r"^[A-Z]CV$|^[FPLT]V$"), "valve", "Control Valve"),
    # alarms and switches (TAHH, PALL, TSH, PSL, TIS, HS) are not controllers; the
    # model called pid14's TAHH-2002B one
    (re.compile(r"^[A-Z]A[HL]{1,2}$"), "instrument", "Alarm"),
    (re.compile(r"^[A-Z]I?S[HL]{0,2}$"), "instrument", "Switch"),
    (re.compile(r"^[A-Z]{1,2}IC$|^[A-Z]C$|^[A-Z][TR]C$|^[A-Z]RIC$"), "controller", "Controller"),
    (re.compile(r"^[A-Z]{1,2}T$"), "transmitter", "Transmitter"),
    (re.compile(r"^[A-Z]{1,2}I$|^[A-Z]G$"), "indicator", "Indicator"),
    (re.compile(r"^[A-Z]E$"), "element", "Primary Element"),
]

_ONE_LETTER_EQUIPMENT = set("VDTPEKMRFCBSXZ")
_PLACEHOLDER_KIND = {"MFM": ("instrument", "Mass Flow Meter"), "MFC": ("controller", "Mass Flow Controller"),
                     "LG": ("indicator", "Level Gauge (Sight Glass)"), "B": ("pump", "Booster Pump"),
                     "R": ("vessel", "Reactor"), "TD": ("instrument", "Temperature Display")}   # vessel, drum, tank, pump, exchanger, compressor, ...

_MODEL_KIND = {
    "vessel": ("vessel", "Vessel"), "tank": ("tank", "Tank"), "column": ("column", "Column"),
    "pump": ("pump", "Pump"), "compressor": ("compressor", "Compressor"),
    "heat_exchanger": ("heat_exchanger", "Heat Exchanger"), "mixer": ("equipment", "Mixer"),
    "filter": ("equipment", "Filter"), "reactor": ("vessel", "Reactor"),
    "control_valve": ("valve", "Control Valve"), "regulator": ("valve", "Pressure Regulator"),
    "hand_valve": ("valve", "Hand / Isolation Valve"), "check_valve": ("valve", "Check Valve"),
    "relief_valve": ("valve", "Relief Valve"), "indicator": ("indicator", "Indicator"),
    "transmitter": ("transmitter", "Transmitter"), "controller": ("controller", "Controller"),
    "element": ("element", "Primary Element"),
}
EQUIPMENT_KINDS = {"vessel", "tank", "column", "pump", "compressor", "heat_exchanger", "equipment", "furnace"}


def normalize_tag(raw: str) -> str:
    """'pi 1084' / 'PI1084' / 'PI_1084' / 'PI–1084' -> 'PI-1084'."""
    t = str(raw or "").upper().strip()
    t = re.sub(r"[\s_–—.:/]+", "-", t)
    t = re.sub(r"-{2,}", "-", t).strip("-")
    t = re.sub(r"^([A-Z]{1,5})(\d)", r"\1-\2", t)
    return t


def _header_tag(raw: str) -> str:
    t = re.sub(r"[^A-Z0-9]+", "-", str(raw or "").upper()).strip("-")
    return t[:40]


_GENERIC_HEADER_TOKENS = {"HEADER", "HDR", "HEADERS", "IN", "OUT", "INLET", "OUTLET", "LINE", "TO", "FROM",
                          "SUPPLY", "RETURN", "CONNECTOR", "OFF", "PAGE"}
_NOT_HEADER_TOKENS = {"REVISION", "REV", "NOTES", "NOTE", "DRAWN", "CHECKED", "APPROVED", "DATE",
                      "SCALE", "SHEET", "TITLE", "COMPANY", "DWG", "PROJECT", "CLIENT"}


#: Drawing annotations the model offered as off-page headers on pid2/pid18:
#: meter types (CORIOLIS, THERMAL, EQUILIBAR), alarm levels (HH, LL), set
#: points (SP, SET), vent-to-atmosphere arrows (ATM), a truncated SIGNAL flag.
_ANNOTATION_WORDS = {"CORIOLIS", "THERMAL", "EQUILIBAR", "HH", "LL", "SP", "SET", "ATM", "SIG",
                     "PSIG", "PSI", "BARG", "GPM", "SCFM", "HC", "ET", "NOTE", "NOTES",
                     "IAS", "VENDOR", "PACKAGE", "JE", "TL", "QUICK", "CONNECT", "THERMOCOUPLE",
                     "MICRON", "FILTER", "DRIP", "LEG", "LOTO", "NOL", "NCL", "SIGHT", "GLASS", "DRAIN",
                     "CLIENT", "ZETON", "CV", "GC", "FUTURE", "BYPASS", "ISOLATION", "INTRODUCTION",
                     "THE", "RELIEF", "AND", "OF", "FOR"}


#: English words that head notes and data blocks ("RANGE 30-70 PSI",
#: "DUTY: 5 KW"); none is an ISA letter code, so "RANGE-30" is never a tag.
_PROSE_PREFIXES = {"RANGE", "SET", "SIZE", "TYPE", "MAX", "MIN", "DUTY", "POWER", "TEMP", "LENGTH",
                   "DESIGN", "VOLUME", "MATL", "CAPACITY", "FLOWRATE", "MAWP", "DWG", "REV", "SHEET"}


def _is_annotation_word(token: str) -> bool:
    import difflib
    if token in _ANNOTATION_WORDS:
        return True
    return len(token) >= 6 and any(len(w) >= 6 and difflib.SequenceMatcher(None, token, w).ratio() >= 0.75
                                   for w in _ANNOTATION_WORDS)


def _is_header_name(tag: str) -> bool:
    """A header name must name something: not a line number (1-1-110), not a
    generic placeholder (HEADER-A) and not title-block text (REVISION-IN),
    all of which a second, noisier read produced on pid2."""
    if _TAG_RE.match(tag) or not re.search(r"[A-Z]{2,}", tag):
        return False
    if re.match(r"^[A-Z]{1,5}-\d{1,6}(-\d+)?$", tag) or re.match(r"^[A-Z0-9]{1,6}-\d{3,}(-|$)", tag):
        return False            # "XY-1" (a truncated tag), "CO2-1003-1" / "RV-1007-1" (line numbers)
    if re.search(r"X{3,}", tag):
        return False            # template placeholders ("T-XXX", "LG-XXXX") are symbols, not headers
    tokens = [t for t in tag.split("-") if t]
    if not any(len(t) >= 3 or re.search(r"\d", t) for t in tokens):
        return False                    # "IH" (a stray interlock-bubble fragment)
    if any(t in _NOT_HEADER_TOKENS or t in _PROSE_PREFIXES for t in tokens):
        return False                  # "VOLUME-2-25-L": a data-block note (pid12), not a flag
    if any(_is_annotation_word(t) for t in tokens if len(t) >= 2)             and not set(tokens) & {"HEADER", "SUPPLY", "RETURN"}:
        return False                  # ("RELIEF-HEADER" on pid15 is a header, "RELIEF-VENT" a note)
    if any(tokens.count(t) >= 3 for t in tokens):
        return False                                  # "PI-1034-TL-TL-TL-...": a looping read
    if len(tokens) >= 2 and tokens[-1].isdigit() and len(tokens[-1]) >= 3:
        return False                                  # "CO2-1004": a line-number fragment
    return any(len(t) >= 2 and t not in _GENERIC_HEADER_TOKENS and re.search(r"[A-Z]", t) for t in tokens)


def classify(tag: str, model_kind: str | None) -> tuple[str, str] | None:
    """(kind, kind_detail) for a tag, preferring its ISA prefix over the
    model's opinion. None when the tag is not a plausible tag."""
    if _PLACEHOLDER_RE.match(tag):
        prefix = tag.split("-")[0]
        if prefix in _PLACEHOLDER_KIND:
            return _PLACEHOLDER_KIND[prefix]
        for pat, kind, detail in _PREFIX_KIND:
            if pat.match(prefix):
                return kind, detail
        return _MODEL_KIND.get(model_kind or "", ("instrument", "Instrument"))
    if model_kind == "header" and not _TAG_RE.match(tag):
        return ("tie_in", "Header / Off-Page Connector") if _is_header_name(tag) else None
    # A well-formed ISA tag the model called a "header" (HS-1001 on pid18)
    # is classified by its prefix like any other tag.
    if not _TAG_RE.match(tag):
        return None
    prefix, number = tag.split("-", 1)
    if prefix in _PROSE_PREFIXES or (len(prefix) >= 4 and prefix in _ANNOTATION_WORDS):
        return None             # "RANGE-30" from "1130 (RANGE 30-70 PSI)" on pid3
    # One-letter prefixes are equipment (V-101, C-102, M-106) with 3+ digits.
    # "H-1001" (a pipe line number read without its spec) and "T-15H" (a
    # heat-trace note) were stored as instruments on pid18.
    if len(prefix) == 1 and (prefix not in _ONE_LETTER_EQUIPMENT or len(re.sub(r"\D", "", number)) < 3
                             or number.startswith("0")):
        return None
    for pat, kind, detail in _PREFIX_KIND:
        if pat.match(prefix):
            return kind, detail
    if model_kind in _MODEL_KIND:
        return _MODEL_KIND[model_kind]
    return ("instrument", "Instrument")


# ═══════════════════════════════════════════════════════════════════════════
# The passes
# ═══════════════════════════════════════════════════════════════════════════

def _map(fn: Callable, items: list, on_timeout: Callable | None = None) -> list:
    """Run fn over items in parallel, giving up on the pass after
    PASS_TIMEOUT_S. Unfinished items get on_timeout(item) (their threads
    are not waited for)."""
    if not items:
        return []
    from concurrent.futures import wait
    ex = ThreadPoolExecutor(max_workers=max(1, min(MAX_WORKERS, len(items))))
    futures = [ex.submit(fn, it) for it in items]
    wait(futures, timeout=PASS_TIMEOUT_S)
    results = []
    for it, fut in zip(items, futures):
        if fut.done() and not fut.cancelled():
            results.append(fut.result())
        else:
            fut.cancel()
            results.append(on_timeout(it) if on_timeout else None)
    ex.shutdown(wait=False, cancel_futures=True)
    return results


def _read_tiles(img, tiles: list[dict], stats: dict) -> list[dict]:
    """Pass 1. Returns raw readings with global pixel positions."""
    def run(tile):
        box = tile["box"]
        crop = img.crop(box)
        png = _png(crop)
        err, merged = None, None
        # Plain read first; the penalties only as a cure for an empty or
        # looping read, because by default they also suppress legitimately
        # repeated prefixes (pid2 lost HV-1032, HV-1083, CK-1059 with them on).
        timeouts = 0
        for sampling in (None, READ_SAMPLING, RETRY_SAMPLING):
            try:
                data = _parse_grounded(
                    _vision_call(_READ_PROMPT, png, 2500, _sampling_for(READ_MODEL, sampling),
                                 **_model_kw(READ_MODEL)),
                    model=READ_MODEL or None, size=crop.size)
            except Exception as exc:
                err = str(exc)[:200]
                timeouts += "timed out" in err.lower()
                if timeouts >= 2:
                    break                      # a slow provider: one retry, not three
                continue
            degenerate = _looks_degenerate(data)
            items = data.get("items") or []
            if degenerate:
                # A looping read repeats one tag at a series of bogus positions;
                # keep its first occurrence only, or the repeats look like
                # several printed copies (pid2: FE-1032A/B, CK-1036A/B).
                items = _first_per_tag(items)
            if merged is None:
                merged = {"items": items}
            else:                                   # a re-read adds only what was missing
                have = {_item_tag(i) for i in merged["items"]}
                merged["items"] += [i for i in _first_per_tag(items) if _item_tag(i) not in have]
            if not degenerate:
                break
        return (tile, merged, None) if merged is not None else (tile, None, err)

    results = list(_map(run, tiles, lambda t: (t, None, "pass timeout")))
    failed = [t for t, data, _e in results if data is None]
    if failed:
        # a burst of connection errors fails all three quick attempts (pid13 L2 lost 9
        # tiles and 21 tags): one more round after a pause
        stats["calls"] += len(failed)
        time.sleep(CONNECT_RETRY_PAUSE_S)
        again = {id(r[0]): r for r in _map(run, failed, lambda t: (t, None, "pass timeout"))}
        results = [again.get(id(r[0]), r) for r in results]
    readings = []
    for tile, data, err in results:
        stats["calls"] += 1
        if data is None:
            stats["failed_tiles"].append({"tile": tile["index"], "error": err})
            continue
        bx0, by0, bx1, by1 = tile["box"]
        seen_in_tile = set()
        for it in data.get("items") or []:
            if isinstance(it, (list, tuple)) and len(it) >= 2:      # compact ["TAG", "kind", x, y]
                it = {"tag": it[0], "kind": it[1],
                      "center": list(it[2:4]) if len(it) >= 4 else None}
            if not isinstance(it, dict):
                continue
            ctr = it.get("center") or it.get("bbox")
            try:
                if isinstance(ctr, (list, tuple)) and len(ctr) == 4:
                    cx, cy = (float(ctr[0]) + float(ctr[2])) / 2, (float(ctr[1]) + float(ctr[3])) / 2
                else:
                    cx, cy = float(ctr[0]), float(ctr[1])
            except Exception:
                cx, cy = 500.0, 500.0
            cx, cy = min(max(cx, 0.0), 1000.0), min(max(cy, 0.0), 1000.0)
            gx = bx0 + cx / 1000.0 * (bx1 - bx0)
            gy = by0 + cy / 1000.0 * (by1 - by0)
            kind = str(it.get("kind") or "").strip().lower()
            raw_tag = str(it.get("tag") or "")
            tag = _header_tag(raw_tag) if kind == "header" else normalize_tag(raw_tag)
            if not tag:
                continue
            key = (tag, round(gx / 50), round(gy / 50))
            if key in seen_in_tile:          # repetition inside one response
                continue
            seen_in_tile.add(key)
            readings.append({"tag": tag, "raw": raw_tag, "kind": kind, "x": gx, "y": gy,
                             "tile": tile["index"]})
    return readings


def _in_core(r: dict, tile: dict) -> bool:
    x0, y0, x1, y1 = tile["core"]
    return x0 <= r["x"] <= x1 and y0 <= r["y"] <= y1


_LETTERS_ONLY = re.compile(r"^[A-Z]{1,5}$")
_NUMBER_ONLY = re.compile(r"^\d{2,6}[A-Z]?$")


def _join_split_bubbles(readings: list[dict], width: int) -> list[dict]:
    """An instrument bubble prints its letters above its number. Some tile
    reads return them as two items ("PSV", "1016"); on pid18 that discarded
    PSV-1016, PSV-1038, PIT-1015 and more. Pair each letters-only item with
    the nearest number-only item BELOW it in the same tile, and emit
    LETTERS-NUMBER; anything left unpaired passes through unchanged."""
    def raw(r):
        return str(r["raw"]).strip().upper()
    letters = [r for r in readings if _LETTERS_ONLY.match(raw(r))]
    numbers = [r for r in readings if _NUMBER_ONLY.match(raw(r))]
    if not letters or not numbers:
        return readings
    reach = 0.03 * width
    used: set[int] = set()
    joined, consumed = [], set()
    for lt in letters:
        cands = [n for n in numbers if id(n) not in used and n["tile"] == lt["tile"]
                 and n["y"] >= lt["y"] - reach * 0.2 and abs(n["x"] - lt["x"]) <= reach
                 and n["y"] - lt["y"] <= reach]
        if not cands:
            continue
        nb = min(cands, key=lambda n: math.hypot(n["x"] - lt["x"], n["y"] - lt["y"]))
        used.add(id(nb))
        consumed.update((id(lt), id(nb)))
        text = f"{raw(lt)}-{raw(nb)}"
        joined.append({**lt, "tag": text, "raw": text, "x": (lt["x"] + nb["x"]) / 2,
                       "y": (lt["y"] + nb["y"]) / 2,
                       "kind": lt["kind"] if lt["kind"] not in ("", "other", "header") else nb["kind"]})
    return [r for r in readings if id(r) not in consumed] + joined


def _merge_readings(readings: list[dict], tiles: list[dict], width: int,
                    stats: dict) -> list[dict]:
    """Classify, drop non-tags, keep each reading only in its owning tile,
    then fuse same-tag readings that are within MERGE_DIST of each other."""
    by_index = {t["index"]: t for t in tiles}
    readings = _join_split_bubbles(readings, width)
    kept = []
    for r in readings:
        if _LINE_NUMBER.search(str(r["raw"])):         # "H-1001 -1/2 -T9L" is a pipe, not a tag
            stats["dropped_not_a_tag"].append(r["raw"])
            stats.setdefault("_texts", []).append({"text": str(r["raw"]), "x": r["x"], "y": r["y"]})
            continue
        raw_up = str(r["raw"]).upper()
        edge = r["x"] < 0.12 * width or r["x"] > 0.88 * width
        header_like = bool(_HEADER_WORDS.search(raw_up)) or (edge and re.search(r"[A-Z]{3,}", raw_up))
        if r.get("kind") in ("note", "line") and not _TAG_RE.match(normalize_tag(raw_up)) and not header_like:
            # (an off-sheet connector box also carries a line number, "RECYCLE GAS | 157-1-140",
            #  so the model may call it "line"; those stay header candidates)
            stats["dropped_not_a_tag"].append(r["raw"])
            stats.setdefault("_texts", []).append({"text": str(r["raw"]), "x": r["x"], "y": r["y"]})
            continue
        if r.get("kind") in ("note", "line") and header_like:
            r["kind"] = "header"
            stats.setdefault("_texts", []).append({"text": str(r["raw"]), "x": r["x"], "y": r["y"]})
        if re.search(r"\b(TO|FROM)\s+[A-Z]{1,5}\s?-\s?\d", raw_up):
            # "REACTOR FEED BYPASS TO FE-1205": an off-sheet reference, not a symbol here
            stats["dropped_not_a_tag"].append(r["raw"])
            stats.setdefault("_texts", []).append({"text": str(r["raw"]), "x": r["x"], "y": r["y"]})
            continue
        split = re.match(r"^\s*([A-Z]{1,5})\s*\(([^)]*)\)\s*(\d{2,6}[A-Z]?)\b(.*)$", raw_up)
        if split:
            # "BPR (EQUILIBAR) 1130 (RANGE 30-70 PSI)": letters, note, number
            r["tag"] = f"{split.group(1)}-{split.group(3)}"
            note = " ".join(x for x in (split.group(2), split.group(4)) if x.strip()).strip(" ()")
            if note:
                stats.setdefault("_texts", []).append({"text": note, "x": r["x"], "y": r["y"]})
        cls = classify(r["tag"], r["kind"])
        if cls is None:
            embedded = _TAG_IN_TEXT.search(str(r["raw"]).upper())
            header = re.sub(r"(-\d+)+$", "", _header_tag(r["raw"]))    # "RECYCLE GAS 157-1-140"
            if embedded:                                  # "M-106 MIXING TUBE"
                r["tag"] = normalize_tag(embedded.group(0))
                rest = str(r["raw"]).upper().replace(embedded.group(0), " ").strip(" -")
                if re.search(r"[A-Z]{3,}", rest):
                    stats.setdefault("_texts", []).append({"text": rest, "x": r["x"], "y": r["y"]})
                cls = classify(r["tag"], None if r["kind"] == "header" else r["kind"])
            elif (r["kind"] == "header" or _HEADER_WORDS.search(r["raw"])) and _is_header_name(header):
                r["tag"] = header
                cls = ("tie_in", "Header / Off-Page Connector")
            if cls is None:
                stats["dropped_not_a_tag"].append(r["raw"])
                stats.setdefault("_texts", []).append({"text": str(r["raw"]), "x": r["x"], "y": r["y"]})
                continue
        r["node_kind"], r["kind_detail"] = cls
        r["owned"] = _in_core(r, by_index[r["tile"]])
        kept.append(r)

    # A reading outside its tile's core is still useful when no owning tile
    # saw that tag nearby (the owning tile may have missed it).
    owned = [r for r in kept if r["owned"]]
    merge_d = MERGE_DIST_FRAC * width
    for r in kept:
        if r["owned"]:
            continue
        if not any(o["tag"] == r["tag"] and math.hypot(o["x"] - r["x"], o["y"] - r["y"]) < 3 * merge_d
                   for o in owned):
            owned.append(r)

    objects: list[dict] = []
    for r in owned:
        for o in objects:
            if o["tag"] == r["tag"] and math.hypot(o["x"] - r["x"], o["y"] - r["y"]) < merge_d:
                o["reads"] += 1
                o["x"] = (o["x"] + r["x"]) / 2
                o["y"] = (o["y"] + r["y"]) / 2
                break
        else:
            objects.append({**r, "reads": 1})
    return objects


def _tag_in_texts(tag: str, texts: list) -> bool:
    norm = {normalize_tag(t) for t in texts if isinstance(t, str)}
    if tag in norm:
        return True
    letters, num = tag.split("-", 1)
    joined = " ".join(str(t).upper() for t in texts)
    return bool(re.search(rf"\b{letters}\W*{num}\b", joined))


def _header_in_texts(tag: str, texts: list) -> bool:
    """A header is confirmed when its naming word (N2, CWS, REACTOR...) is
    transcribed nearby; "PRIOLIS" (a misread of CORIOLIS) is not."""
    words = [t for t in tag.split("-") if len(t) >= 2 and t not in _GENERIC_HEADER_TOKENS]
    joined = " ".join(str(t).upper() for t in texts)
    return bool(words) and all(re.search(r"\b" + re.escape(w), joined) for w in words[:1])


def _verify(img, objects: list[dict], width: int, stats: dict) -> list[dict]:
    """Pass 2. Re-read the drawing in small cells (half a reading tile) WITHOUT
    telling the model what to expect; a candidate is kept only if its cell
    (or a neighbouring cell, for tags on a cell edge) transcribes it. One
    call per occupied cell rather than one per tag. Headers are free text
    and are kept without verification."""
    W, H = img.size
    cell = TILE_TARGET_PX / 2
    cols, rows = max(1, math.ceil(W / cell)), max(1, math.ceil(H / cell))
    cw, ch = W / cols, H / rows
    margin = 0.15

    def cell_of(o):
        return min(cols - 1, int(o["x"] // cw)), min(rows - 1, int(o["y"] // ch))

    # A tag read independently by two tiles (the two grids) is confirmed; the
    # cell transcription wrongly rejected PI-1015, PIT-1015 and PSV-1023 on pid13.
    confirmed = [o for o in objects if o.get("reads", 1) >= 2]
    candidates = [o for o in objects if o.get("reads", 1) < 2]
    occupied = sorted({cell_of(o) for o in candidates})

    def run(cr):
        c, r = cr
        box = (max(0, int((c - margin) * cw)), max(0, int((r - margin) * ch)),
               min(W, int((c + 1 + margin) * cw)), min(H, int((r + 1 + margin) * ch)))
        png = _png(img.crop(box))
        for sampling in (None, READ_SAMPLING):
            try:
                texts = _parse_json(_vision_call(_VERIFY_PROMPT, png, 1200, _sampling_for(VERIFY_MODEL, sampling),
                                                 **_model_kw(VERIFY_MODEL))).get("texts") or []
            except Exception:
                return cr, None
            strs = [str(t) for t in texts]
            if not (len(strs) >= 10 and len(set(strs)) / len(strs) < 0.5):
                return cr, texts
        return cr, None             # still looping: cannot check this cell, so do not reject

    texts_by_cell = {}
    for cr, texts in _map(run, occupied, lambda cr: (cr, None)):
        stats["calls"] += 1
        texts_by_cell[cr] = texts
        if texts is None:
            stats["verify_errors"] += 1

    verified, rejected = list(confirmed), []
    for o in confirmed:
        o["check"] = "two_reads"            # how the tag was confirmed (the review queue reads it)
    for o in candidates:
        c, r = cell_of(o)
        own = texts_by_cell.get((c, r))
        if own is None:                     # could not check -> keep, counted above
            o["check"] = "unchecked"
            verified.append(o)
            continue
        near = [texts_by_cell.get((c + dc, r + dr)) or [] for dc in (-1, 0, 1) for dr in (-1, 0, 1)]
        check = _header_in_texts if o["node_kind"] == "tie_in" else _tag_in_texts
        if check(o["tag"], own) or any(check(o["tag"], t) for t in near):
            o["check"] = "transcription"
            verified.append(o)
        else:
            rejected.append(o)
    # a second, closer look at each rejected tag: a half-tile cell holds dozens of
    # bubbles and its transcription skips some (LLM-only L1 lost PI-1015 / PIT-1015 on
    # pid13, TE-3014 / TE-3015 / TW-3000 on pid15). The crop is centred on the reading
    # and the model is again not told what to expect.
    second = _reverify(img, [o for o in rejected if o["node_kind"] != "tie_in"][:REVERIFY_MAX], W, stats)
    for o in rejected:
        if id(o) in second:
            o["check"] = "second_look"
            verified.append(o)
            stats.setdefault("reverified", []).append(o["tag"])
        else:
            stats["dropped_unverified"].append(o["tag"])
    return verified


REVERIFY_MAX = 40
REVERIFY_HALF_FRAC = 0.04       # crop half-size, as a fraction of the sheet width


def _reverify(img, objects: list[dict], width: float, stats: dict) -> set[int]:
    """ids of the objects whose tag a tight crop round their reading transcribes."""
    W, H = img.size
    half = REVERIFY_HALF_FRAC * width

    def run(o):
        box = (int(max(0, o["x"] - half)), int(max(0, o["y"] - half)),
               int(min(W, o["x"] + half)), int(min(H, o["y"] + half)))
        try:
            texts = _parse_json(_vision_call(_VERIFY_PROMPT, _png(img.crop(box)), 400,
                                             **_model_kw(VERIFY_MODEL))).get("texts") or []
        except Exception:
            return o, None
        return o, texts

    ok = set()
    for o, texts in _map(run, objects, lambda o: (o, None)):
        stats["calls"] += 1
        if texts is not None and _tag_in_texts(o["tag"], texts):
            ok.add(id(o))
    return ok


GRID_STRIDE = 10000          # tile index = grid * GRID_STRIDE + position in that grid


def _grid_of(o: dict) -> int:
    return int(o.get("tile", 0)) // GRID_STRIDE


TITLE_BAND_FRAC = 0.15     # equipment callouts ("C-102 CO2 COMPRESSOR ...") sit in the top band


def _drop_title_callouts(objects: list[dict], height: float) -> list[dict]:
    """Many P&IDs repeat each equipment tag in a callout block along the top
    of the sheet (pid18: V-103, C-102, C-104). A copy in that band is a
    callout, not a second unit, when the same tag is also read lower down."""
    band = TITLE_BAND_FRAC * height
    lower = {o["tag"] for o in objects if o["node_kind"] in EQUIPMENT_KINDS and o["y"] > band}
    # a placeholder in the title band ("M-XXX MASS FLOW CONTROLLER") is a legend entry
    return [o for o in objects
            if not (o["node_kind"] in EQUIPMENT_KINDS and o["y"] <= band and o["tag"] in lower)
            and not (is_placeholder(o["tag"]) and o["y"] <= band)]


def _dedupe_names(objects: list[dict], width: float | None = None) -> list[dict]:
    """Resolve a tag read at more than one place. Returns the kept objects.

    The drawing is read with more than one tile grid. A tag that is really
    printed twice (two cylinders both labelled V-104, HV-1065 on pid2) is
    seen twice by EVERY grid; a spurious double depends on where one grid's
    tile edges fall. So the number of copies kept is the smallest number any
    grid that saw the tag agrees on. Within a grid:
      instruments - readings from different tiles are one object seen twice
                    (positions are approximate: pid2's PI-1078 became A/B);
                    only several readings in ONE tile count as distinct;
      equipment / headers - each reading is a distinct unit.
    Interlock reference bubbles are never split.
    Copies are named V-104A / V-104B (top-left first); a header printed
    twice becomes -IN / -OUT by side of the sheet (left-to-right flow)."""
    if not width:
        width = max((o.get("x", 0) for o in objects), default=0) / 0.95 or 5100
    objects = _drop_fragment_headers(objects, width)
    groups: dict[str, list[dict]] = {}
    for o in objects:
        groups.setdefault(o["tag"], []).append(o)
    merge_gap = MERGE_DIST_FRAC * max(width, 1)
    dropped: set[int] = set()
    for tag, grp in groups.items():
        if is_placeholder(tag):
            # every placeholder occurrence is its own symbol: PI-XXXX-1, PI-XXXX-2 ...
            grp.sort(key=lambda o: (round(o["y"] / 200), o["x"]))
            for i, o in enumerate(grp):
                o["tag"] = f"{tag}-{i + 1}"
                o["placeholder"] = True
            continue
        if len(grp) >= 2:
            per_unit = grp[0]["node_kind"] in EQUIPMENT_KINDS | {"tie_in"}
            candidates = {}                               # grid -> the copies it claims
            for g in {_grid_of(o) for o in grp}:
                mine = [o for o in grp if _grid_of(o) == g]
                if not per_unit:
                    by_tile: dict[int, list[dict]] = {}
                    for o in mine:
                        by_tile.setdefault(o.get("tile", -1), []).append(o)
                    mine = max(by_tile.values(), key=len)
                candidates[g] = mine
            # With fabricated coordinates the smallest count any grid agreed on was
            # the safe choice; with grounded positions it merged pid2's real
            # V-101A/B whenever one grid missed a cylinder. Now: the grid that saw
            # the most clearly separate copies (> MERGE_DIST_FRAC of the width apart).
            def separate(objs):
                kept_ = []
                for o in sorted(objs, key=lambda o: (o["y"], o["x"])):
                    if all(math.hypot(o["x"] - k["x"], o["y"] - k["y"]) > merge_gap for k in kept_):
                        kept_.append(o)
                return kept_
            candidates = {g: separate(v) for g, v in candidates.items()}
            best = max(candidates, key=lambda g: (len(candidates[g]), -g))
            keep = candidates[best]
            dropped.update(id(o) for o in grp if not any(o is k for k in keep))
            grp[:] = keep
        if _INTERLOCK_REF.match(tag.split("-")[0]):
            # an interlock bubble (IHT-3031A) is printed wherever the interlock
            # acts and again in the cause list: one interlock, never split and
            # never cloned from its printed copies (round 2 made IHT-3001A/B/C)
            if len(grp) >= 2:
                keep1 = max(grp, key=lambda o: o.get("reads", 1))
                dropped.update(id(o) for o in grp if o is not keep1)
                grp[:] = [keep1]
        if len(grp) < 2:
            continue
        grp.sort(key=lambda o: (o["x"], o["y"]))
        if grp[0]["node_kind"] == "tie_in":
            if len(grp) == 2 and (grp[0]["x"] < width / 2) != (grp[1]["x"] < width / 2):
                grp[0]["tag"], grp[1]["tag"] = f"{tag}-IN", f"{tag}-OUT"
            else:                       # pid14: two "TO REACTOR" flags, both on the right edge
                for i, o in enumerate(sorted(grp, key=lambda o: (o["y"], o["x"]))):
                    o["tag"] = f"{tag}-{i + 1}"
            continue
        grp.sort(key=lambda o: (round(o["x"] / 200), o["y"]))
        for i, o in enumerate(grp):
            # TE-1036A printed twice -> TE-1036A-1 / -2, never "TE-1036AA"
            o["tag"] = f"{tag}-{i + 1}" if tag[-1].isalpha() else f"{tag}{chr(ord('A') + i)}"
    return [o for o in objects if id(o) not in dropped]


def _drop_fragment_headers(objects: list[dict], width: float) -> list[dict]:
    """A two-line flag label read once whole and once in part ("METERED" and
    "METERED-H2" on pid14) is one flag: drop a header whose words begin
    another header's words when the two sit together."""
    heads = [o for o in objects if o["node_kind"] == "tie_in"]
    frag = set()
    for a in heads:
        wa = a["tag"].split("-")
        for b in heads:
            wb = b["tag"].split("-")
            if a is not b and len(wa) < len(wb) and wb[:len(wa)] == wa \
                    and math.hypot(a["x"] - b["x"], a["y"] - b["y"]) < 0.03 * width:
                frag.add(id(a))
    return [o for o in objects if id(o) not in frag]


#: Interlock / cause-and-effect reference bubbles (IHT, IHTS, IHP, ICTH, ICPL,
#: IHA, IHL, IN ...): the same interlock is drawn at every place it acts.
_INTERLOCK_REF = re.compile(r"^I(C|H)[A-Z]{1,3}$|^IN$")


CONNECT_RETRY_PAUSE_S = 10
#: Draw each listed item on the tile (a red box and its number) and name items by
#: number ("set-of-mark" visual prompting) instead of by coordinates alone.
CONNECT_MARKS = os.getenv("BROWNFIELD_CONNECT_MARKS", "0").strip().lower() in ("1", "true", "yes")

_CONNECT_MARKS_PROMPT = """This is ONE TILE of a larger P&ID drawing. Each tagged item read in it is marked
on the image with a red box and a red number:
{tags}

Trace every pipe run and every instrument signal line in this tile. For each run, list the marked
items it passes through IN ORDER from one end to the other, following the drawn lines only. Where a
run branches, start a new run at the branch point, beginning with the last item before the branch.
Skip runs that pass no marked item. Answer with the item NUMBERS.

Respond with compact JSON only: {{"runs": [[1, 4, 2], [4, 7]]}}"""


def _marked_tile(img, box, inside: list[dict]) -> bytes:
    """The tile with each item's label boxed in red and numbered 1..n."""
    from PIL import ImageDraw, ImageFont
    x0, y0, x1, y1 = box
    tile = img.crop(box).convert("RGB")
    d = ImageDraw.Draw(tile)
    side = max(x1 - x0, y1 - y0)
    r = max(14, int(0.03 * side))           # ~45 px on a 1500 px tile: around the bubble, not on its text
    font = ImageFont.load_default(size=max(14, int(0.024 * side)))
    for i, o in enumerate(inside, 1):
        cx, cy = o["x"] - x0, o["y"] - y0
        if o.get("extent"):                                  # the part of the body in this tile
            ex0, ey0, ex1, ey1 = o["extent"]
            bx0, by0 = max(ex0, x0) - x0, max(ey0, y0) - y0
            bx1, by1 = min(ex1, x1) - x0, min(ey1, y1) - y0
            d.rectangle([bx0, by0, bx1, by1], outline=(230, 0, 0), width=3)
            cx, cy = bx0 + r, by0 + r
        else:
            d.rectangle([cx - r, cy - r, cx + r, cy + r], outline=(230, 0, 0), width=2)
        label = str(i)
        tw, th = d.textbbox((0, 0), label, font=font)[2:]
        tx, ty = cx - r - tw - 4, cy - r - th - 2
        d.rectangle([tx - 2, ty - 1, tx + tw + 2, ty + th + 3], fill=(255, 255, 255))
        d.text((tx, ty), label, fill=(230, 0, 0), font=font)
    buf = io.BytesIO()
    tile.save(buf, format="PNG")
    return buf.getvalue()


def _connect(img, tiles: list[dict], objects: list[dict], stats: dict,
             model: str | None = None) -> list[tuple[str, str, str]]:
    """Pass 3. Per tile: which of the known tags visible here are joined."""
    def run(tile):
        x0, y0, x1, y1 = tile["box"]
        inside = [o for o in objects if x0 <= o["x"] <= x1 and y0 <= o["y"] <= y1
                  or (o.get("extent") and o["extent"][0] < x1 and o["extent"][2] > x0
                      and o["extent"][1] < y1 and o["extent"][3] > y0)]
        here = [o["tag"] for o in inside]
        if len(here) < 2:
            return tile, here, {}, None
        if CONNECT_MARKS:
            listing = "\n".join(f"{i}: {o['tag']}" for i, o in enumerate(inside, 1))
            prompt, png = _CONNECT_MARKS_PROMPT.format(tags=listing), _marked_tile(img, tile["box"], inside)
        else:
            listing = "\n".join(f"- {o['tag']} at {int((min(max(o['x'], x0), x1) - x0) / max(1, x1 - x0) * 1000)},"
                                f"{int((min(max(o['y'], y0), y1) - y0) / max(1, y1 - y0) * 1000)}"
                                + (" (its body extends across this tile)" if o.get("extent") else "")
                                for o in inside)
            prompt, png = _CONNECT_PROMPT.format(tags=listing), _png(img.crop(tile["box"]))
        try:
            try:
                use = model or CONNECT_MODEL
                raw = _vision_call(prompt, png, 1200, model=use) if use \
                    else _vision_call(prompt, png, 1200)
            except Exception:                       # larger model unavailable: use the reading model
                raw = _vision_call(prompt, png, 1200)
        except Exception as exc:
            return tile, here, None, str(exc)[:200]
        data = _parse_json(raw)
        if CONNECT_MARKS:                                   # numbers back to tags
            num = {str(i): o["tag"] for i, o in enumerate(inside, 1)}
            data = {"runs": [[num.get(str(t).strip(), str(t)) for t in run_]
                             for run_ in data.get("runs") or [] if isinstance(run_, (list, tuple))]}
        return tile, here, data, None

    edges: dict[tuple[str, str], str] = {}
    results = list(_map(run, tiles, lambda t: (t, ["", ""], None, "pass timeout")))
    failed = [r[0] for r in results if len(r[1]) >= 2 and r[2] is None]
    if failed:
        # connection drops come in bursts (pid13 L1: 57 of 60 tiles "Connection error."):
        # one more try after a pause before a tile's links are given up
        stats["calls"] += len(failed)
        time.sleep(CONNECT_RETRY_PAUSE_S)
        again = {id(r[0]): r for r in _map(run, failed, lambda t: (t, ["", ""], None, "pass timeout"))}
        results = [again.get(id(r[0]), r) for r in results]
    for tile, here, data, err in results:
        if len(here) < 2:
            continue
        stats["calls"] += 1
        stats["connect_tiles"] = stats.get("connect_tiles", 0) + 1
        if data is None:
            stats["failed_tiles"].append({"tile": tile["index"], "pass": "connect", "error": err})
            continue
        allowed = set(here)
        pairs = list(data.get("connections") or [])
        for run_ in data.get("runs") or []:                     # ordered run -> consecutive pairs
            if isinstance(run_, (list, tuple)):
                seq = [str(t) for t in run_ if isinstance(t, (str, int))]
                pairs += [[a, b, "process"] for a, b in zip(seq, seq[1:])]
        for c in pairs:
            if not isinstance(c, (list, tuple)) or len(c) < 2:
                continue
            a, b = str(c[0]).strip().upper(), str(c[1]).strip().upper()
            if a not in allowed:
                a = normalize_tag(a)
            if b not in allowed:
                b = normalize_tag(b)
            if a not in allowed or b not in allowed or a == b:
                stats["dropped_edges_unknown_tag"] += 1
                continue
            kind = str(c[2]).lower() if len(c) > 2 else "process"
            key = (a, b) if a < b else (b, a)
            edges.setdefault(key, kind if kind in ("process", "utility", "signal") else "process")
    return [(a, b, k) for (a, b), k in edges.items()]


#: Ask the model where each equipment item's drawn body is, so a tile that shows part of a
#: vessel lists it even when the vessel's label is elsewhere (pid15: the FIC-302x feeds and
#: thermowells along R-301's wall were never linked to it - its label was in other tiles).
CONNECT_EXTENTS = os.getenv("BROWNFIELD_CONNECT_EXTENTS", "0").strip().lower() in ("1", "true", "yes")

_EXTENT_PROMPT = """This is a complete P&ID drawing. For each equipment item below, give the bounding box of its
DRAWN SYMBOL (the outline of the vessel, reactor, tank, exchanger, pump, compressor or package) - not of its
tag text. Coordinates are 0-1000 relative to this image. Leave out an item you cannot find.
Items (tag: where its tag is printed, 0-1000):
{items}

Respond with JSON only: {{"extents": [{{"tag": "TAG", "bbox_2d": [x1, y1, x2, y2]}}]}}"""


def _equipment_extents(img, objects: list[dict], stats: dict) -> None:
    """Set o["extent"] (x0, y0, x1, y1 in sheet pixels) on each equipment item the
    model can outline. The box must contain or touch the item's label."""
    from PIL import Image
    eq = [o for o in objects if o["node_kind"] in EQUIPMENT_KINDS]
    if not eq:
        return
    W, H = img.size
    small = img.copy()
    small.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    items = "\n".join(f"- {o['tag']}: {int(o['x'] / W * 1000)},{int(o['y'] / H * 1000)}" for o in eq)
    try:
        model = CONNECT_MODEL or None
        raw = _vision_call(_EXTENT_PROMPT.format(items=items), _png(small), 1500, model=model,
                           timeout=LONG_CALL_TIMEOUT_S) if model else \
            _vision_call(_EXTENT_PROMPT.format(items=items), _png(small), 1500)
        stats["calls"] += 1
    except Exception as exc:
        stats["failed_tiles"].append({"pass": "extents", "error": str(exc)[:200]})
        return
    by_tag = {o["tag"]: o for o in eq}
    found = 0
    for it in _parse_json(raw).get("extents") or []:
        o = by_tag.get(str(it.get("tag", "")).strip()) if isinstance(it, dict) else None
        box = it.get("bbox_2d") if o else None
        try:
            x0, y0, x1, y1 = (float(v) for v in box)
        except (TypeError, ValueError):
            continue
        x0, x1 = sorted((x0 / 1000 * W, x1 / 1000 * W))
        y0, y1 = sorted((y0 / 1000 * H, y1 / 1000 * H))
        pad = 0.02 * W                                       # the label sits beside its symbol
        if not (x0 - pad <= o["x"] <= x1 + pad and y0 - pad <= o["y"] <= y1 + pad):
            continue                                         # a box for some other shape
        if (x1 - x0) * (y1 - y0) > 0.25 * W * H:
            continue                                         # "the whole sheet"
        o["extent"] = (x0, y0, x1, y1)
        found += 1
    stats["equipment_extents"] = found


def _overview(img, objects: list[dict], stats: dict) -> dict:
    """Pass 4. Title and system/subsystem grouping on a downscaled sheet."""
    from PIL import Image
    small = img.copy()
    small.thumbnail((2400, 2400), Image.Resampling.LANCZOS)
    tags = [o["tag"] for o in objects]
    eq = [o["tag"] for o in objects if o["node_kind"] in EQUIPMENT_KINDS]
    prompt = _OVERVIEW_PROMPT.format(tags=", ".join(tags), eq=", ".join(eq) or "(none)")
    data = {}
    for model in ([CONNECT_MODEL] if CONNECT_MODEL else []) + [None]:
        try:
            data = _parse_json(_vision_call(prompt, _png(small), 3000, model=model, timeout=LONG_CALL_TIMEOUT_S)
                               if model else _vision_call(prompt, _png(small), 3000))
            stats["calls"] += 1
        except Exception as exc:
            stats["failed_tiles"].append({"pass": "overview", "error": str(exc)[:200]})
            continue
        if data.get("subsystems") or data.get("systems"):
            break
    if data.get("subsystems") and not data.get("systems"):          # compact form
        data["systems"] = [{"name": data.get("system") or "Main Process System",
                            "subsystems": [{"name": sub[0], "members": sub[1] if len(sub) > 1 else []}
                                           for sub in data["subsystems"]
                                           if isinstance(sub, (list, tuple)) and sub]}]
    known, used = set(tags), set()
    systems = []
    for s in data.get("systems") or []:
        if not isinstance(s, dict) or not s.get("name"):
            continue
        subs = []
        for sub in s.get("subsystems") or []:
            if isinstance(sub, str):
                subs.append({"name": sub, "members": []})
                continue
            if not isinstance(sub, dict) or not sub.get("name"):
                continue
            members = [m for m in (sub.get("members") or []) if m in known and m not in used]
            used.update(members)
            subs.append({"name": str(sub["name"])[:120], "members": members})
        systems.append({"name": str(s["name"])[:120], "subsystems": subs})
    descriptions = {}
    for item in data.get("equipment") or []:
        if isinstance(item, (list, tuple)) and len(item) >= 2 and str(item[0]).upper() in known:
            descriptions[str(item[0]).upper()] = str(item[1])[:120]
    return {"drawing_title": str(data.get("drawing_title") or "")[:200], "systems": systems,
            "equipment_descriptions": descriptions}


def consensus_edges(per_grid: list[list[tuple[str, str, str]]], per_grid_tiles: list[list[dict]],
                    pos: dict[str, tuple[float, float]],
                    seen_by: dict[tuple[str, str], int] | None = None) -> list[tuple[str, str, str]]:
    """Keep a connection only if every grid that COULD see it reported it.

    A grid could see A-B when one of its tiles contains both items; a grid
    that never had them in one tile has no opinion. On pid2 (235B model)
    one grid gave 77-79% connection precision; agreement of two gave 89% at
    the same F1 (69%) - a wrong connection costs a retrofit more than a
    missing one."""
    if not per_grid:
        return []

    def in_tile(t, tag):
        p = pos[tag]
        if len(p) == 6:                                      # x, y and the body's extent
            return t["box"][0] <= p[0] <= t["box"][2] and t["box"][1] <= p[1] <= t["box"][3] or \
                (p[2] < t["box"][2] and p[4] > t["box"][0] and p[3] < t["box"][3] and p[5] > t["box"][1])
        return t["box"][0] <= p[0] <= t["box"][2] and t["box"][1] <= p[1] <= t["box"][3]

    def could_see(tiles, a, b):
        if a not in pos or b not in pos:
            return False
        return any(in_tile(t, a) and in_tile(t, b) for t in tiles)

    keyed = [{(a, b) if a < b else (b, a): k for a, b, k in g} for g in per_grid]
    out: dict[tuple[str, str], str] = {}
    for key in set().union(*keyed):
        a, b = key
        voters = [gi for gi, tiles in enumerate(per_grid_tiles) if could_see(tiles, a, b)] or \
                 [gi for gi, k in enumerate(keyed) if key in k]
        if all(key in keyed[gi] for gi in voters):
            out[key] = next(k[key] for k in keyed if key in k)
            if seen_by is not None:
                seen_by[key] = len(voters)      # 1: only one grid could check it
    return [(a, b, out[(a, b)]) for a, b in sorted(out)]


def drop_skipping_edges(edges: list[tuple[str, str, str]], pos: dict[str, tuple[float, float]],
                        stats: dict | None = None, tol: float = 0.25) -> list[tuple[str, str, str]]:
    """Remove A-B when the model ALSO reported A-C and C-B and C lies between
    A and B: the model skipped the item in between (V-103 -> CK-1035 next to
    V-103 -> HV-1032 -> CK-1035 on pid2). On pid2 this raised connection
    precision from 53% to 58% at the cost of 3 of 101 edges."""
    nb: dict[str, set[str]] = {}
    for a, b, _k in edges:
        nb.setdefault(a, set()).add(b)
        nb.setdefault(b, set()).add(a)

    def between(a, b, c):
        if a not in pos or b not in pos or c not in pos:
            return False
        (ax, ay), (bx, by), (cx, cy) = pos[a], pos[b], pos[c]
        abx, aby = bx - ax, by - ay
        l2 = abx * abx + aby * aby
        if l2 <= 0:
            return False
        t = ((cx - ax) * abx + (cy - ay) * aby) / l2
        if not 0.05 < t < 0.95:
            return False
        px, py = ax + t * abx, ay + t * aby
        return math.hypot(cx - px, cy - py) <= tol * math.sqrt(l2) + 8

    kept = [(a, b, k) for a, b, k in edges
            if not any(between(a, b, c) for c in nb[a] & nb[b])]
    if stats is not None:
        stats["dropped_skipping_edges"] = len(edges) - len(kept)
    return kept


def drop_cross_loop_controller_edges(edges: list[tuple[str, str, str]], kinds: dict[str, str],
                                     stats: dict | None = None) -> list[tuple[str, str, str]]:
    """A controller exchanges signals only within its own loop (ISA-5.1: same
    loop number). The model often wired controller bubbles to whatever sat
    nearby (FIC-1085 to PI-1076, PI-1077, HV-1031 and the CO2 header on pid2).
    Dropping controller connections across loop numbers raised pid2
    connection precision from 70% to 78% without losing a correct one."""
    def loop_no(tag: str) -> str | None:
        m = re.search(r"-(\d{2,6})", tag)
        return m.group(1) if m else None

    kept = [(a, b, k) for a, b, k in edges
            if not ((kinds.get(a) == "controller" or kinds.get(b) == "controller")
                    and loop_no(a) != loop_no(b))]
    if stats is not None:
        stats["dropped_cross_loop_edges"] = len(edges) - len(kept)
    return kept


def drop_interlock_chains(edges: list[tuple[str, str, str]], kinds: dict[str, str],
                          stats: dict | None = None) -> list[tuple[str, str, str]]:
    """Interlock reference bubbles (IHT-3001, ICTH-2001B ...) are a cause list
    drawn as a block of touching ovals; the model traced the block as a pipe
    (IHT-3001 -> IHT-3002 -> ... -> IHT-4002 on pid14). A bubble is joined to
    the device that trips it: its own loop number, or a controller / switch /
    alarm / relay the cause list hangs from. Nothing joins two bubbles."""
    def ref(t):
        return bool(_INTERLOCK_REF.match(t.split("-")[0]))

    def loop_no(t):
        m = re.search(r"-(\d{2,6})", t)
        return m.group(1) if m else None

    def trips(t):
        letters = t.split("-")[0]
        return kinds.get(t) == "controller" or bool(re.search(r"[SAY]", letters[1:]))

    def reader_of(element):
        """The loop's instrument an element's signal goes to (TE-3011 -> TI-3011): an
        interlock hangs from that, not from the element (LLM-only pid15 drew
        IHT-30xx -> TE-30xx thirteen times, skipping the TI between)."""
        letters, num = element.split("-", 1)
        cands = [t for t in kinds if t != element and "-" in t and t.split("-", 1)[1] == num
                 and not ref(t) and t[0] == letters[0]
                 and re.fullmatch(r"[A-Z](I|IT|T|IC|IS|ISH|ISL|IA|IAH|IAL|C|TC|RC)", t.split("-")[0])]
        return sorted(cands, key=lambda t: (t.split("-")[0][1:2] != "I", len(t)))[0] if cands else None

    kept, seen = [], set()
    for a, b, k in edges:
        if ref(a) and ref(b):
            continue
        if ref(a) or ref(b):
            other = b if ref(a) else a
            if kinds.get(other) in EQUIPMENT_KINDS | {"tie_in"}:
                continue
            if loop_no(a) != loop_no(b) and not trips(other):
                continue
            if other.split("-")[0].endswith("E") and reader_of(other):
                bubble, reader = (a if ref(a) else b), reader_of(other)
                a, b = (bubble, reader) if bubble < reader else (reader, bubble)
                if stats is not None:
                    stats.setdefault("interlocks_moved_to_reader", []).append(f"{bubble}:{other}->{reader}")
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        kept.append((a, b, k))
    if stats is not None:
        stats["dropped_interlock_edges"] = len(edges) - len(kept)
    return kept


def add_indicator_taps(edges: list[tuple[str, str, str]], kinds: dict[str, str],
                       stats: dict | None = None) -> list[tuple[str, str, str]]:
    """A pressure/temperature indicator TAPS a line; it is not in series with
    it. The model draws PCV-1082 - PI-1084 - HV-1082 as a chain; the line
    actually runs PCV-1082 - HV-1082 with PI-1084 on a tap. Join the
    non-indicator items on either side of every indicator. On pid2 this
    raised connection recall from 57% to 65%.
    Signal links do not count: TE-3002 -> TI-3002 -> IHT-3002 is a signal chain, and
    "rejoining" TE-3002 to the interlock bubble undid drop_interlock_chains
    (LLM-only pid15 L2: 26 such links)."""
    adj: dict[str, set[str]] = {}
    for a, b, k in edges:
        if k == "signal" or _INTERLOCK_REF.match(a.split("-")[0]) or _INTERLOCK_REF.match(b.split("-")[0]):
            continue
        adj.setdefault(a, set()).add(b)
        adj.setdefault(b, set()).add(a)
    have = {(a, b) if a < b else (b, a) for a, b, _k in edges}
    added = []
    for p, nb in adj.items():
        if kinds.get(p) != "indicator" or len(nb) < 2:
            continue
        for a, b in itertools.combinations(sorted(n for n in nb if kinds.get(n) != "indicator"), 2):
            key = (a, b) if a < b else (b, a)
            if key not in have:
                have.add(key)
                added.append((key[0], key[1], "process"))
    if stats is not None:
        stats["added_tap_edges"] = len(added)
    return list(edges) + added


def _header_pass(img, objects: list[dict], stats: dict) -> list[tuple[str, str, str]]:
    """Headers run the full width of the sheet with their label at the edge, so
    no tile ever shows a header together with the branches leaving it. Each
    header gets one full-width strip. Its answer is trusted only when the two
    flags of the same line name EACH OTHER as the far end; then the upstream
    (left) flag connects to the branches both reports agree on, and to the
    other flag. On pid2 that added 5 header connections, all correct, while
    the one-sided answers for the crowded lower headers were mostly wrong."""
    W, H = img.size
    heads = [o for o in objects if o["node_kind"] == "tie_in"]
    if len(heads) < 2:
        return []

    def run(h):
        y0, y1 = max(0, int(h["y"] - 0.13 * H)), min(H, int(h["y"] + 0.33 * H))
        inside = [o for o in objects if y0 <= o["y"] <= y1 and o is not h]
        listing = "\n".join(f"- {o['tag']} at {int(o['x'] / W * 1000)},{int((o['y'] - y0) / max(1, y1 - y0) * 1000)}"
                            for o in inside)
        prompt = _HEADER_PROMPT.format(hdr=h["tag"], hx=int(h["x"] / W * 1000),
                                       hy=int((h["y"] - y0) / max(1, y1 - y0) * 1000), tags=listing)
        png = _png(img.crop((0, y0, W, y1)))
        raw = None
        for attempt in range(2):
            try:
                raw = _vision_call(prompt, png, 800, model=CONNECT_MODEL) if CONNECT_MODEL and attempt == 0 \
                    else _vision_call(prompt, png, 800, model=CONNECT_MODEL or None)
                break
            except Exception as exc:
                stats.setdefault("header_errors", []).append(f"{h['tag']}: {str(exc)[:80]}")
        if raw is None:
            return h["tag"], [], None
        d = _parse_json(raw)
        allowed = {o["tag"] for o in inside}
        on = [t for t in (str(x).strip().upper() for x in d.get("on_line") or []) if t in allowed]
        oe = str(d.get("other_end") or "").strip().upper()
        return h["tag"], on, (oe if oe in allowed else None)

    results = {}
    for tag, on, oe in _map(run, heads, lambda h: (h["tag"], [], None)):
        stats["calls"] += 1
        results[tag] = (on, oe)
    x_of = {o["tag"]: o["x"] for o in objects}
    out: dict[tuple[str, str], str] = {}
    head_tags = set(results)

    def names(a: str, b: str) -> bool:
        """a's answer points at b - as the far end or listed on the line
        (the model sometimes puts the far flag in the list and itself as
        'other_end', as N2-HEADER-OUT did on pid2)."""
        on, oe = results.get(a, ([], None))
        return oe == b or b in on

    y_of = {o["tag"]: o["y"] for o in objects}

    def spans_sheet(a: str, b: str) -> bool:
        """A header runs between two flags at opposite sheet edges on one
        horizontal line (pid2's N2 header). Mid-sheet connectors such as
        CWS/CWR next to an exchanger are not headers; their long answers
        named each other and produced 16 wrong connections."""
        xa, xb = x_of.get(a, 0), x_of.get(b, 0)
        left, right = min(xa, xb), max(xa, xb)
        return left < 0.2 * W and right > 0.8 * W and abs(y_of.get(a, 0) - y_of.get(b, 0)) < 0.06 * H

    for tag, other in itertools.combinations(sorted(head_tags), 2):
        if not (names(tag, other) and names(other, tag) and spans_sheet(tag, other)):
            continue                                            # flags must name each other
        upstream = min((tag, other), key=lambda t: x_of.get(t, 0))
        common = (set(results[tag][0]) & set(results[other][0])) - head_tags
        for t in common:
            out[tuple(sorted((upstream, t)))] = "process"
        out[tuple(sorted((tag, other)))] = "process"
    stats["header_edges"] = len(out)
    return [(a, b, k) for (a, b), k in sorted(out.items())]


def correct_from_loop_pattern(objects: list[dict], evidence: set[str] | None = None) -> list[tuple[str, str]]:
    """Resolve an illegible instrument tag from the plant's own loop pattern.

    pid2 prints its sixth flow controller smudged ("F C / 10 52"); every
    other flow stack on the sheet is FIC / FTC / FE. When at least two other
    loops share one letter pattern exactly, and this loop matches it except
    for ONE tag whose letters are one insertion/deletion/substitution away,
    that tag is renamed to the pattern's letters (same loop number). Returns
    [(old, new)] so the caller can flag each one as inferred, not read."""
    import difflib
    def split(tag):
        m = re.match(r"^([A-Z]{1,5})-(\d{2,6})([A-Z]?)$", tag)
        return (m.group(1), m.group(2)) if m and not m.group(3) else (None, None)

    loops: dict[str, dict[str, dict]] = {}
    for o in objects:
        if o["node_kind"] in EQUIPMENT_KINDS | {"tie_in"}:
            continue
        letters, num = split(o["tag"])
        if letters and num:
            # group by loop number AND measured variable: HV-1032 shares the
            # number of flow loop 1032 but is not part of it
            loops.setdefault(f"{num}/{letters[0]}", {})[letters] = o
    patterns: dict[frozenset, list[str]] = {}
    for num, members in loops.items():
        if len(members) >= 2:
            patterns.setdefault(frozenset(members), []).append(num)
    changes = []
    for num, members in loops.items():
        mine = set(members)
        for pat, nums in patterns.items():
            if len(nums) < 2 or num in nums or len(pat) != len(mine):
                continue
            # The odd pattern must be unique: pid18 uses {PI, PIT} in some loops
            # and {PI, PT} in four others - both are real conventions.
            if len(patterns.get(frozenset(mine), [])) > 1:
                continue
            missing, extra = pat - mine, mine - pat
            if len(missing) != 1 or len(extra) != 1:
                continue
            want, have = next(iter(missing)), next(iter(extra))
            ops = [op for op in difflib.SequenceMatcher(None, have, want).get_opcodes() if op[0] != "equal"]
            if len(ops) != 1 or max(ops[0][2] - ops[0][1], ops[0][4] - ops[0][3]) != 1:
                continue
            new_tag = f"{want}-{num.split('/')[0]}"
            # ... and the drawing itself must have shown the corrected tag at
            # least once (pid2: one tile read FIC-1032; verification rejected it)
            if evidence is not None and new_tag not in evidence:
                continue
            if any(o["tag"] == new_tag for o in objects):
                continue
            o = members[have]
            changes.append((o["tag"], new_tag))
            o["tag"] = new_tag
            if o["node_kind"] not in ("controller",) and want.endswith("C"):
                o["node_kind"], o["kind_detail"] = "controller", "Controller"
            break
    return changes


# ═══════════════════════════════════════════════════════════════════════════
# Text of symbols and connections: read where printed, inferred where not
# ═══════════════════════════════════════════════════════════════════════════

_ISA_VARIABLE = {"A": "Analysis", "B": "Burner", "C": "Conductivity", "D": "Density", "E": "Voltage",
                 "F": "Flow", "G": "Gauging", "H": "Hand", "I": "Current", "J": "Power", "K": "Time",
                 "L": "Level", "M": "Moisture", "P": "Pressure", "Q": "Quantity", "R": "Radiation",
                 "S": "Speed", "T": "Temperature", "U": "Multivariable", "V": "Vibration", "W": "Weight",
                 "Y": "Event", "Z": "Position"}
_ISA_NOUN = {"I": "Indicator", "C": "Controller", "T": "Transmitter", "E": "Element", "V": "Valve",
             "S": "Switch", "Y": "Relay", "G": "Gauge", "R": "Recorder", "A": "Alarm", "Q": "Totalizer"}
_ISA_ADJ = {"I": "Indicating", "C": "Control", "T": "Transmitting", "R": "Recording", "S": "Safety",
            "A": "Alarm", "Q": "Totalizing"}
_ISA_SPECIAL = {"CK": "Check Valve", "NRV": "Non-Return Valve", "HV": "Hand Valve", "XV": "On/Off Valve",
                "BPR": "Back Pressure Regulator", "PCV": "Pressure Control Valve / Regulator",
                "PSV": "Pressure Safety Valve", "PRV": "Pressure Relief Valve", "RV": "Relief Valve",
                "HS": "Hand Switch", "TP": "Tie-In Point", "FAN": "Fan"}


def isa_description(tag: str) -> str | None:
    """ISA-5.1 name generated from a tag's letters: FIC -> "Flow Indicating
    Controller", PIT -> "Pressure Indicating Transmitter", FE -> "Flow Element".
    None when the letters are not an instrument code."""
    letters = tag.split("-")[0]
    if letters in _ISA_SPECIAL:
        return _ISA_SPECIAL[letters]
    if len(letters) < 2 or letters[0] not in _ISA_VARIABLE or letters[-1] not in _ISA_NOUN:
        return None
    middle = [_ISA_ADJ.get(c) for c in letters[1:-1]]
    if any(m is None for m in middle):
        return None
    return " ".join([_ISA_VARIABLE[letters[0]], *middle, _ISA_NOUN[letters[-1]]])


_REPAIR_PROMPT = """This is a small crop of a P&ID drawing. At its centre the number {num} was read without its
letters. Read the COMPLETE tag that this number belongs to, exactly as printed: in an instrument bubble the letters
are printed above the number; beside a valve the tag is printed on one line (HV-1114, CK-1124). Never add letters
that are not printed. If you cannot read the letters, or the number is not part of a tag (a line number, a range,
a note), answer null.

Respond with JSON only: {{"tag": "LETTERS-{num}"}} or {{"tag": null}}"""


_SYMBOL_PROMPT = """This is ONE TILE of a P&ID drawing. List EVERY piping component symbol drawn in it, INCLUDING symbols
that have NO tag printed next to them. Symbol kinds:
hand_valve, check_valve, control_valve, three_way_valve, solenoid_valve, pressure_regulator, relief_valve,
back_pressure_regulator, filter, flow_meter, sight_glass, vessel, pump, compressor, reactor, heat_exchanger.
Count every symbol separately - three identical valves are three items.
Report only symbols that are clearly drawn: not text, not line crossings, arrowheads or line breaks, and not
the same symbol twice. If you are not sure a symbol is there, leave it out.

Output a JSON list. Each entry: "bbox_2d": [x1, y1, x2, y2] of the SYMBOL, "kind": its kind, "text": the
text printed next to it (null if none).
Respond with JSON only: [{{"bbox_2d": [x1, y1, x2, y2], "kind": "kind", "text": null}}]"""

_UNTAGGED_KIND = {
    "hand_valve": ("HV", "valve", "Hand Valve"), "check_valve": ("CK", "valve", "Check Valve"),
    "control_valve": ("CV", "valve", "Control Valve"), "three_way_valve": ("XV", "valve", "Three-Way Valve"),
    "solenoid_valve": ("XY", "valve", "Solenoid Valve"), "pressure_regulator": ("PCV", "valve", "Pressure Regulator"),
    "relief_valve": ("PSV", "valve", "Relief Valve"), "back_pressure_regulator": ("BPR", "valve", "Back Pressure Regulator"),
    "filter": ("F", "equipment", "Filter"), "flow_meter": ("FM", "instrument", "Flow Meter"),
    "sight_glass": ("LG", "indicator", "Sight Glass"), "vessel": ("V", "vessel", "Vessel"),
    "pump": ("P", "pump", "Pump"), "compressor": ("C", "compressor", "Compressor"),
    "reactor": ("R", "vessel", "Reactor"), "heat_exchanger": ("E", "heat_exchanger", "Heat Exchanger")}


def needs_untagged_pass(objects: list[dict]) -> bool:
    """Template-like sheets: few numbered tags, or many placeholders. On fully
    tagged sheets (pid2/3/13/18) the pass is skipped, so it cannot regress them."""
    numbered = sum(1 for o in objects if _TAG_RE.match(o["tag"]))
    placeholders = sum(1 for o in objects if o.get("placeholder"))
    mode = os.getenv("BROWNFIELD_UNTAGGED_SYMBOLS", "auto").strip().lower()
    if mode in ("0", "off", "false", "no"):
        return False
    if mode in ("1", "on", "true", "yes"):
        return True
    return numbered < 30 or placeholders >= 5


def _untagged_symbols(img, tiles: list[dict], objects: list[dict], stats: dict) -> list[dict]:
    """Inventory every drawn symbol per tile and add those no tag accounts for
    (a template's hand valves, regulators, filters ...) as HV-U01, PCV-U02 ...
    flagged untagged=True. A symbol is 'accounted for' when a read tag of the
    same family sits within 2% of the sheet width."""
    W, H = img.size

    def run(tile):
        try:
            raw = _vision_call(_SYMBOL_PROMPT, _png(img.crop(tile["box"])), 3500, **_model_kw(SYMBOL_MODEL))
        except Exception as exc:
            return tile, None, str(exc)[:120]
        g = _parse_grounded(raw, text_key="text", model=SYMBOL_MODEL or None,
                            size=(tile["box"][2] - tile["box"][0], tile["box"][3] - tile["box"][1]))
        # grounded items are [text, kind, x, y]; the loop below expects [kind, text, x, y]
        return tile, {"symbols": g.get("symbols") or [[k, t, x, y] for t, k, x, y in g.get("items", [])]}, None

    found = []
    for tile, data, err in _map(run, tiles, lambda t: (t, None, "pass timeout")):
        stats["calls"] += 1
        if data is None:
            stats["failed_tiles"].append({"tile": tile["index"], "pass": "symbols", "error": err})
            continue
        bx0, by0, bx1, by1 = tile["box"]
        for it in data.get("symbols") or []:
            if not isinstance(it, (list, tuple)) or len(it) < 4 or str(it[0]) not in _UNTAGGED_KIND:
                continue
            try:
                gx = bx0 + float(it[2]) / 1000 * (bx1 - bx0)
                gy = by0 + float(it[3]) / 1000 * (by1 - by0)
            except (TypeError, ValueError):
                continue
            if not _in_core({"x": gx, "y": gy}, tile) or gy <= TITLE_BAND_FRAC * H:
                continue
            text = str(it[1] or "").strip()
            if text and (_TAG_RE.match(normalize_tag(text)) or _TAG_IN_TEXT.search(text.upper())):
                continue                                      # tagged: the reading pass owns it
            found.append({"kind": str(it[0]), "text": "" if text.lower() in ("null", "none") else text,
                          "x": gx, "y": gy})
    fam = lambda k: _UNTAGGED_KIND[k][1]
    out, counters = [], {}
    near = 0.02 * W
    for f in sorted(found, key=lambda f: (f["y"], f["x"])):
        prefix, node_kind, detail = _UNTAGGED_KIND[f["kind"]]
        if any(math.hypot(o["x"] - f["x"], o["y"] - f["y"]) < near and
               (o["node_kind"] == node_kind or o["node_kind"] in EQUIPMENT_KINDS and node_kind in EQUIPMENT_KINDS)
               for o in objects + out):
            continue
        counters[prefix] = counters.get(prefix, 0) + 1
        tag = f"{prefix}-U{counters[prefix]:02d}"
        out.append({"tag": tag, "raw": f["text"], "kind": f["kind"], "node_kind": node_kind,
                    "kind_detail": detail + (f" ({f['text']})" if f["text"] else ""),
                    "x": f["x"], "y": f["y"], "tile": -1, "reads": 1, "untagged": True,
                    "note": f["text"]})
    stats["untagged_symbols"] = len(out)
    return out


def drop_references_and_line_fragments(objects: list[dict], texts: list[dict], width: float,
                                       stats: dict | None = None) -> list[dict]:
    """Two kinds of text that look like tags but are not symbols on this sheet:
      - the start of a printed line number next to it ("RV-1007" of
        "RV-1007 -1/2 -T049.316-NI", pid13);
      - an off-sheet reference: "BYPASS TO FE-1205" (pid3), also when "TO"
        and the tag were read as separate pieces."""
    near = 0.05 * width
    label_reach = 0.15 * width          # a long line label's centre can be far from its first word
    drop = set()
    for t in texts:
        text = re.sub(r"\s+", " ", str(t["text"]).upper()).strip()
        info = parse_line_label(text)
        if info and info.get("line_no"):
            head = normalize_tag(re.match(r"^[A-Z0-9]{1,6}\s?-\s?\d{2,6}", info["line_no"]).group(0)) \
                if re.match(r"^[A-Z0-9]{1,6}\s?-\s?\d{2,6}", info["line_no"]) else None
            for o in objects:
                if head and o["tag"] == head and math.hypot(o["x"] - t["x"], o["y"] - t["y"]) < label_reach:
                    drop.add(id(o))
        for m in re.finditer(r"\b(?:TO|FROM)\s+([A-Z]{1,5}\s?-\s?\d{2,6}[A-Z]?)", text):
            ref = normalize_tag(m.group(1))
            drop.update(id(o) for o in objects if o["tag"] == ref)
        if re.search(r"\b(TO|FROM)$", text):
            for o in objects:
                if _TAG_RE.match(o["tag"]) and 0 <= o["x"] - t["x"] < near and abs(o["y"] - t["y"]) < 0.015 * width:
                    drop.add(id(o))
    kept = [o for o in objects if id(o) not in drop]
    if stats is not None and drop:
        stats["dropped_references"] = sorted(o["tag"] for o in objects if id(o) in drop)
    return kept


def _repair_orphan_numbers(img, objects: list[dict], texts: list[dict], stats: dict) -> list[dict]:
    """A bubble's number read without its letters ("1016" on pid13, five
    times, next to FI/FIT/FE/DI bubbles) is re-read in a tight crop. The
    answer is accepted only if it ends in that number and is a valid tag."""
    W, H = img.size
    orphans = []
    for t in texts:
        num = str(t["text"]).strip()
        if not re.fullmatch(r"\d{3,6}[A-Z]?", num):
            continue
        if any(o["tag"].endswith("-" + num) and math.hypot(o["x"] - t["x"], o["y"] - t["y"]) < 0.02 * W
               for o in objects):
            continue                                         # its tag was read after all
        if any(p["num"] == num and math.hypot(p["x"] - t["x"], p["y"] - t["y"]) < 0.015 * W for p in orphans):
            continue
        # a cut-off read of a neighbour's number ("101" beside IHP-1015 on pid13,
        # "repaired" into a phantom IHP-101)
        if any(re.sub(r"^.*-", "", o["tag"]).startswith(num) and len(re.sub(r"^.*-", "", o["tag"])) > len(num)
               and math.hypot(o["x"] - t["x"], o["y"] - t["y"]) < 0.03 * W for o in objects):
            continue
        orphans.append({"num": num, "x": t["x"], "y": t["y"]})
    if not orphans:
        return []
    half = 0.03 * W

    def run(o):
        box = (int(max(0, o["x"] - half)), int(max(0, o["y"] - half)),
               int(min(W, o["x"] + half)), int(min(H, o["y"] + half)))
        try:
            raw = _vision_call(_REPAIR_PROMPT.format(num=o["num"]), _png(img.crop(box)), 60)
        except Exception:
            return o, None
        return o, _parse_json(raw).get("tag")

    out, have = [], {x["tag"] for x in objects}
    for o, tag in _map(run, orphans[:40], lambda o: (o, None)):
        stats["calls"] += 1
        tag = normalize_tag(tag) if isinstance(tag, str) else ""
        if not tag.endswith("-" + o["num"]) or tag in have:
            continue
        cls = classify(tag, None)
        if cls is None or cls[0] in EQUIPMENT_KINDS:
            continue
        have.add(tag)
        out.append({"tag": tag, "raw": tag, "kind": "", "node_kind": cls[0], "kind_detail": cls[1],
                    "x": o["x"], "y": o["y"], "tile": -1, "reads": 1, "owned": True})
    return out


def infer_final_elements(objects: list[dict], texts: list[dict], width: float) -> list[dict]:
    """Create the unlabelled final control element of a loop from its printed
    annotation. pid2 prints "FC CORIOLIS" / "FC THERMAL" beside an unlabelled
    valve under each FIC/FTC/FE stack; the valve is loop n's control valve,
    i.e. FCV-n (the reference names them exactly so). Returned objects carry
    inferred=True and are added BEFORE the connection pass so the model can
    trace runs through them."""
    by_loop: dict[tuple[str, str], list[dict]] = {}
    for o in objects:
        m = re.match(r"^([A-Z])[A-Z]{0,4}-(\d{2,6})$", o["tag"])
        if m and o["node_kind"] not in EQUIPMENT_KINDS | {"tie_in"}:
            by_loop.setdefault((m.group(1), m.group(2)), []).append(o)
    have = {o["tag"] for o in objects}
    out = []
    for t in texts:
        m = re.match(r"^\s*([A-Z])C\b\s*(.*)$", str(t["text"]).upper())
        if not m:
            continue
        var, rest = m.group(1), m.group(2).strip()
        cands = [(math.hypot(o["x"] - t["x"], o["y"] - t["y"]), num)
                 for (v, num), members in by_loop.items() if v == var
                 and any(x["node_kind"] == "controller" for x in members)
                 for o in members]
        if not cands:
            continue
        d, num = min(cands)
        tag = f"{var}CV-{num}"
        if d > 0.08 * width or tag in have:
            continue
        if any(re.match(rf"^{var}[A-Z]{{0,2}}V-{num}$", h) for h in have):
            continue                         # the loop's valve is already tagged (FV-1017)
        have.add(tag)
        detail = f"{_ISA_VARIABLE.get(var, var)} Control Valve" + (f" ({rest.title()})" if rest else "")
        out.append({"tag": tag, "raw": t["text"], "kind": "control_valve", "node_kind": "valve",
                    "kind_detail": detail, "x": t["x"], "y": t["y"], "tile": -1, "reads": 1,
                    "inferred": True, "note": rest.title()})
    return out


def attach_annotations(objects: list[dict], texts: list[dict], width: float) -> None:
    """Printed words next to a symbol describe it: MIXING TUBE -> M-106,
    EQUILIBAR -> BPR-1063, CORIOLIS -> the Coriolis valve. Each text goes to
    the nearest symbol within 5% of the sheet width."""
    for t in texts:
        text = re.sub(r"\s+", " ", str(t["text"]).upper()).strip(" -")
        if (not re.search(r"[A-Z]{3,}", text) or _LINE_NUMBER.search(text) or _TAG_RE.match(normalize_tag(text))
                or re.match(r"^[A-Z]C\b", text)):
            continue
        near = [(math.hypot(o["x"] - t["x"], o["y"] - t["y"]), o) for o in objects if o["node_kind"] != "tie_in"]
        if not near:
            continue
        d, o = min(near, key=lambda x: x[0])
        own = o["tag"].split("-")[0]
        text = " ".join(w for w in text.split() if w != own and not w.isdigit())
        if d <= 0.05 * width and re.search(r"[A-Z]{3,}", text):
            words = text.title()
            notes = o.setdefault("notes", [])
            if words not in notes:
                notes.append(words)


def connection_kind(a: dict, b: dict) -> str:
    """ISA meaning of a connection from what it joins (the reference's rules):
    signal  - within one loop, element/transmitter/controller to each other or
              a controller to its control valve
    impulse - an indicator tapping a valve or line
    utility - a utility header (cooling water, steam, instrument air)
    process - everything else"""
    ka, kb = a.get("node_kind"), b.get("node_kind")
    if any(_INTERLOCK_REF.match(o["tag"].split("-")[0]) for o in (a, b)):
        return "signal"                       # an interlock trip is a software / wired signal
    num = lambda o: (re.search(r"-(\d{2,6})", o["tag"]) or [None, None])[1]
    same_loop = num(a) is not None and num(a) == num(b)
    instr = {"controller", "transmitter", "element"}
    if same_loop and ({ka, kb} <= instr or ({ka, kb} & {"controller"} and {ka, kb} & {"valve"})):
        return "signal"
    if same_loop and {ka, kb} == {"element", "indicator"}:
        return "signal"                       # TE-2001B -> TI-2001B: a sensor feeding its readout
    if "indicator" in (ka, kb) and ({ka, kb} & {"valve"}):
        valve = a if ka == "valve" else b
        # a gauge after a regulator / control / hand valve senses through an
        # impulse line; next to a check valve it sits on the run (reference: 11/11)
        if not valve["tag"].startswith(("CK-", "NRV-")):
            return "impulse"
    utility = re.compile(r"\b(CWS|CWR|CW|STEAM|STM|IA|IAS|UTILITY|COOLING)\b")
    if any(o.get("node_kind") == "tie_in" and utility.search(o["tag"].replace("-", " ")) for o in (a, b)):
        return "utility"
    return "process"


_SIZE = re.compile(r'(\d+(?:\s*/\s*\d+)?|\d+\s+\d+/\d+)\s*["”]')
_BARE_SIZE = re.compile(r"-\s*(\d+/\d+)\s*-")
# Piping specs: "T9L" (pid18) and "T035.316-NI" (pid13: class.material-coating)
_SPEC = re.compile(r"\b(T\d{1,3}(?:\.[A-Z0-9]+(?:-[A-Z]{1,3})?|[A-Z]))(?![A-Z0-9.])")


def parse_line_label(text: str) -> dict | None:
    """'H-1007 -1/2 -T9L' -> number H-1007, size 1/2", spec T9L;
    'CO2-1004 -1/2 -T9L -HC-0.5' -> + insulation/tracing HC-0.5;
    '1/2" X 1/4"' -> a size change (reducer); '1-1-110' -> line number."""
    t = re.sub(r"\s+", " ", str(text).upper()).strip()
    if re.search(r"\b\d+\s*-\s*\d+\s*(PSIG|PSI|BARG|BAR|KPA|DEG|C|F|%)\b", t) or \
            re.search(r"\b(SET|RANGE)\b", t):
        return None                     # "0-600 PSIG", "SET @ 100 psig": instrument ranges, not lines
    sizes = [re.sub(r"\s", "", x) + '"' for x in _SIZE.findall(t)] or \
            [x + '"' for x in _BARE_SIZE.findall(t)]
    if re.fullmatch(r'[\d/ "”]+X[\d/ "”]+', t.replace(" ", "")):
        return {"size": " x ".join(sizes), "note": "size change (reducer)"}
    m = re.match(r"^([A-Z0-9]{1,6}-\d{2,6})", t.replace(" ", ""))
    if re.fullmatch(r"\d+-\d+-\d+", t.replace(" ", "")):
        return {"line_no": t.replace(" ", "")}
    if not m and not sizes:
        return None
    out = {}
    if m:
        out["line_no"] = t.replace(" ", "")
        out["fluid"] = m.group(1).split("-")[0]
    if sizes:
        out["size"] = sizes[0]
    spec = _SPEC.search(t)
    if spec:
        out["spec"] = spec.group(1)
    return out


def _join_label_pieces(texts: list[dict], width: float) -> list[dict]:
    """A line label read in pieces ("H2-1001", "-1/4", "-T035.316-NI" on
    pid14) is one label: a piece starting with "-" is appended to the nearest
    text to its left on the same row. Pieces are chained left to right."""
    out = [dict(t) for t in sorted(texts, key=lambda t: t["x"])]
    joined = set()
    for i, t in enumerate(out):
        if not str(t["text"]).strip().startswith("-"):
            continue
        left = [j for j in range(i) if j not in joined and abs(out[j]["y"] - t["y"]) < 0.006 * width
                and 0 <= t["x"] - out[j]["x"] < 0.08 * width
                and not str(out[j]["text"]).strip().startswith("-")]
        if left:
            j = max(left, key=lambda j: out[j]["x"])
            out[j]["text"] = f"{out[j]['text']} {str(t['text']).strip()}"
            joined.add(i)
    return [t for i, t in enumerate(out) if i not in joined]


def attach_line_labels(lines: list[dict], texts: list[dict], pos_px: dict, width: float) -> int:
    """Printed line numbers / sizes go to the nearest connection (point-to-
    segment distance between the label and the two symbols) within 5% of the
    sheet width. Returns how many labels were attached."""
    def seg_dist(px, py, a, b):
        (ax, ay), (bx, by) = a, b
        dx, dy = bx - ax, by - ay
        L2 = dx * dx + dy * dy
        t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / L2))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))
    attached = 0
    seen = set()
    for t in _join_label_pieces(texts, width):
        info = parse_line_label(t["text"])
        if not info:
            continue
        key = (json.dumps(info, sort_keys=True), round(t["x"] / 60), round(t["y"] / 60))
        if key in seen:
            continue
        seen.add(key)
        cands = [(seg_dist(t["x"], t["y"], pos_px[l["from_tag"]], pos_px[l["to_tag"]]), l)
                 for l in lines if l["from_tag"] in pos_px and l["to_tag"] in pos_px]
        if not cands:
            continue
        d, line = min(cands, key=lambda x: x[0])
        if d > 0.05 * width:
            continue
        # a line number with a fluid code (H2-1001-1/4-T035.316-NI) outranks a bare
        # sheet reference (157-1-110 in the flag box at the same pipe's end: pid14)
        lettered = lambda s: bool(re.match(r"^[A-Z]", str(s or "")))
        if info.get("line_no") and (not line.get("printed_line_no")
                                    or (lettered(info["line_no"]) and not lettered(line["printed_line_no"]))):
            line["line_id"] = line["printed_line_no"] = info["line_no"]
        if info.get("size") and not line.get("size"):
            line["size"] = info["size"]
        for k in ("spec", "fluid", "note"):
            if info.get(k):
                line[k] = info[k]
        attached += 1
    return attached


def add_controller_valve_links(edges: list[tuple[str, str, str]], objects: list[dict],
                               stats: dict | None = None) -> list[tuple[str, str, str]]:
    """ISA: a loop's controller (xIC) drives its final control element (xCV /
    xV) with the same loop number. The model rarely draws that signal line
    between a bubble and an unlabelled valve; add it when both exist."""
    have = {(a, b) if a < b else (b, a) for a, b, _k in edges}
    by_num: dict[str, list[str]] = {}
    for o in objects:
        m = re.match(r"^([A-Z]{1,5})-(\d{2,6})$", o["tag"])
        if m:
            by_num.setdefault(m.group(2), []).append(o["tag"])
    added = []
    for num, tags in by_num.items():
        ctl = [t for t in tags if re.match(r"^[A-Z]I?C-", t)]
        valves = [t for t in tags if re.match(r"^[A-Z]C?V-", t) and not t.startswith(("HV-", "CK-"))]
        linked = lambda a: {y for x, y in have if x == a} | {x for x, y in have if y == a}
        for c in ctl[:1]:
            for v in valves:
                key = (c, v) if c < v else (v, c)
                # the drawing routes it through the loop's relay / positioner
                # (pid13: FIC-1017 -> FY-1017 -> FV-1017): no direct link then
                relayed = any(r.split("-")[0].endswith("Y") and r.split("-", 1)[1] == num
                              for r in linked(v))
                if c[0] == v[0] and key not in have and not relayed:
                    have.add(key)
                    added.append((key[0], key[1], "signal"))
    if stats is not None:
        stats["added_controller_links"] = len(added)
    return list(edges) + added


def route_through_relays(edges: list[tuple[str, str, str]], stats: dict | None = None) -> list[tuple[str, str, str]]:
    """ISA: a switch / controller drives a valve through the loop's relay or
    solenoid (xY). A signal traced straight from HS-1002 to XV-1002 passed the
    3-way solenoid body that XY-1002 labels (pid13); when that relay is tied to
    the valve, the switch's signal goes to the relay."""
    num = lambda t: t.split("-", 1)[1] if "-" in t else ""
    pre = lambda t: t.split("-", 1)[0]
    have = {(a, b) if a < b else (b, a) for a, b, _k in edges}
    out, moved = [], []
    for a, b, k in edges:
        if k != "process" and num(a) and num(a) == num(b):
            for c, v in ((a, b), (b, a)):
                if not (re.fullmatch(r"HS|[A-Z]I?C|[A-Z]RC", pre(c)) and re.fullmatch(r"[A-Z]C?V", pre(v))):
                    continue
                relays = [r for x, y in have for r in (x, y) if v in (x, y) and r != v
                          and re.fullmatch(r"[A-Z]Y", pre(r)) and num(r) == num(v)]
                if len(relays) == 1:
                    key = (c, relays[0]) if c < relays[0] else (relays[0], c)
                    if key not in have:
                        have.add(key)
                        out.append((c, relays[0], k))
                    moved.append(f"{c}->{relays[0]}")
                    break
            else:
                out.append((a, b, k))
            continue
        out.append((a, b, k))
    if stats is not None and moved:
        stats["relayed_signals"] = moved
    return out


def derive_loops(tags: list[str]) -> list[dict]:
    """ISA loops from numbering: tags sharing a loop number form a control
    loop when one of them is a controller; members are the tags of that
    controller's measured variable (first letter)."""
    by_num: dict[str, list[str]] = {}
    for t in tags:
        if _TAG_RE.match(t):
            letters, num = t.split("-", 1)
            by_num.setdefault(re.sub(r"[A-Z]$", "", num), []).append(t)
    loops = []
    for num, members in sorted(by_num.items()):
        ctrls = [m for m in members if (classify(m, None) or ("",))[0] == "controller"]
        if not ctrls:
            continue
        variable = ctrls[0][0]
        loop_members = sorted(m for m in members if m[0] == variable)
        if len(loop_members) >= 2:
            loops.append({"loop_id": num, "service": f"{variable} control loop {num}",
                          "members": loop_members})
    return loops


# ═══════════════════════════════════════════════════════════════════════════
# Analysis cache (so rebuild never re-runs the model for the same drawing)
# ═══════════════════════════════════════════════════════════════════════════

def _cache_file(pid: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", pid)[:120] or "default"
    return _CACHE_DIR / f"{safe}.json"


def _save_cache(pid: str, digest: str, analysis: dict) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(pid).write_text(json.dumps({"sha256": digest, "analysis": analysis}),
                                    encoding="utf-8")
    except Exception as exc:
        logger.debug(f"[VisionService] cache write failed for {pid}: {exc}")


def load_cached_analysis(pid: str, digest: str | None = None) -> dict | None:
    """The last analysis of this project's drawing, if it is still the same file."""
    try:
        data = json.loads(_cache_file(pid).read_text(encoding="utf-8"))
    except Exception:
        return None
    if digest is None:
        _p, f_bytes, _m = resolve_uploaded_drawing(pid)
        if not f_bytes:
            return None
        digest = hashlib.sha256(f_bytes).hexdigest()
    return data.get("analysis") if data.get("sha256") == digest else None


# ═══════════════════════════════════════════════════════════════════════════
# Public: analyse
# ═══════════════════════════════════════════════════════════════════════════

def drop_port_labels(objects: list[dict], width: float, stats: dict | None = None) -> list[dict]:
    """A bare utility code in the middle of the sheet ("CWS" / "CWR" at a
    chiller's ports on pid15, printed at 0.805 W) labels a nozzle, not an
    off-sheet flag; flags sit at the sheet edges (pid13 / pid15: beyond 0.88 W
    or within 0.12 W) or carry a header word."""
    def label(o):
        words = o["tag"].split("-")
        return (o["node_kind"] == "tie_in" and 0.15 * width < o["x"] < 0.85 * width and len(o["tag"]) <= 4
                and not set(words) & {"HEADER", "SUPPLY", "RETURN", "TO", "FROM"})

    kept = [o for o in objects if not label(o)]
    if stats is not None and len(kept) < len(objects):
        stats["dropped_port_labels"] = [o["tag"] for o in objects if label(o)]
    return kept


#: The sheet-wide header pass. Off: LLM-only on pid13 it added 53 links for 2 right ones
#: (a star from the AIR flag to everything on its strip; connection F1 67.0% without it,
#: 50.7% with), and on other runs it returned nothing at all.
HEADER_PASS = os.getenv("BROWNFIELD_HEADER_PASS", "0").strip().lower() in ("1", "true", "yes")

#: Check each proposed connection on a crop showing both ends, the two items marked, before
#: it is kept (precision: the tile pass links items that are merely near each other).
CONNECT_VERIFY = os.getenv("BROWNFIELD_CONNECT_VERIFY", "0").strip().lower() in ("1", "true", "yes")
VERIFY_EDGE_MAX_PX = 1600

_EDGE_VERIFY_PROMPT = """This is a crop of a P&ID drawing. Item A ({a}) is marked with a RED box and the letter A;
item B ({b}) with a BLUE box and the letter B. Other tagged items are marked with grey numbered boxes.

Question: is A connected to B by a drawn line - a pipe (solid line) or an instrument signal line (dashed,
dotted or solid) - that runs from A to B WITHOUT passing through any other marked item on the way?
Lines that merely cross each other do not connect. Follow the drawn line carefully from one to the other.

Respond with JSON only: {{"connected": true}} or {{"connected": false}}"""


def _edge_crop(img, a: dict, b: dict, others: list[dict]) -> bytes:
    """The region around A and B, A in red, B in blue, other items in grey."""
    from PIL import Image, ImageDraw, ImageFont
    W, H = img.size
    pts = []
    for o in (a, b):
        pts.append((o["x"], o["y"]))
        if o.get("extent"):
            ex0, ey0, ex1, ey1 = o["extent"]
            # the body's nearest part to the other end: the whole box would be the sheet
            other = b if o is a else a
            pts.append((min(max(other["x"], ex0), ex1), min(max(other["y"], ey0), ey1)))
    pad = 0.035 * W
    x0 = int(max(0, min(p[0] for p in pts) - pad)); x1 = int(min(W, max(p[0] for p in pts) + pad))
    y0 = int(max(0, min(p[1] for p in pts) - pad)); y1 = int(min(H, max(p[1] for p in pts) + pad))
    crop = img.crop((x0, y0, x1, y1)).convert("RGB")
    scale = min(1.0, VERIFY_EDGE_MAX_PX / max(crop.size))
    if scale < 1.0:
        crop = crop.resize((max(1, int(crop.width * scale)), max(1, int(crop.height * scale))), Image.Resampling.LANCZOS)
    d = ImageDraw.Draw(crop)
    r = max(10, int(0.0075 * W * scale))               # around a bubble, off the lines entering it
    font = ImageFont.load_default(size=max(12, int(0.8 * r)))

    def mark(o, colour, label, width):
        if o.get("extent"):
            ex0, ey0, ex1, ey1 = o["extent"]
            box = [(max(ex0, x0) - x0) * scale, (max(ey0, y0) - y0) * scale,
                   (min(ex1, x1) - x0) * scale, (min(ey1, y1) - y0) * scale]
        else:
            cx, cy = (o["x"] - x0) * scale, (o["y"] - y0) * scale
            box = [cx - r, cy - r, cx + r, cy + r]
        d.rectangle(box, outline=colour, width=width)
        tw, th = d.textbbox((0, 0), label, font=font)[2:]
        tx, ty = box[0], box[1] - th - 3                     # above the box: pipes enter from the sides
        d.text((tx, ty), label, fill=colour, font=font)

    for i, o in enumerate(others, 1):
        if x0 <= o["x"] <= x1 and y0 <= o["y"] <= y1:
            mark(o, (150, 150, 150), str(i), 1)
    mark(a, (220, 0, 0), "A", 3)
    mark(b, (0, 70, 230), "B", 3)
    buf = io.BytesIO()
    crop.save(buf, format="PNG")
    return buf.getvalue()


def verify_edges(img, edges: list[tuple[str, str, str]], objects: list[dict],
                 stats: dict) -> list[tuple[str, str, str]]:
    """Keep a connection unless the model, shown both ends marked, says no line joins
    them. An unanswered check keeps the connection."""
    by_tag = {o["tag"]: o for o in objects}

    def run(e):
        a, b = by_tag.get(e[0]), by_tag.get(e[1])
        if a is None or b is None:
            return e, None
        others = [o for o in objects if o is not a and o is not b]
        prompt = _EDGE_VERIFY_PROMPT.format(a=a["tag"], b=b["tag"])
        png = _edge_crop(img, a, b, others)
        try:
            raw = _vision_call(prompt, png, 40, model=CONNECT_MODEL) if CONNECT_MODEL \
                else _vision_call(prompt, png, 40)
        except Exception:
            try:
                raw = _vision_call(prompt, png, 40)
            except Exception:
                return e, None
        v = _parse_json(raw).get("connected")
        return e, v if isinstance(v, bool) else None

    kept, dropped = [], []
    for e, verdict in _map(run, edges, lambda e: (e, None)):
        stats["calls"] += 1
        (dropped if verdict is False else kept).append(e)
    stats["edges_rejected_by_check"] = [f"{a}-{b}" for a, b, _k in dropped]
    return kept


#: Ask, for each item, which items the lines leaving it lead to (a crop centred on it).
#: "off", "mutual" (links both ends name, added to the tile pass) or "any".
CONNECT_NEIGHBOURS = os.getenv("BROWNFIELD_CONNECT_NEIGHBOURS", "off").strip().lower()
NEIGHBOUR_HALF_FRAC = 0.07      # crop half-size, as a fraction of the sheet width

_NEIGHBOUR_PROMPT = """This is a crop of a P&ID drawing centred on the item {tag}, marked with a RED box.
Tagged items in this crop (label position as x,y in 0-1000 relative to this crop):
{tags}

Follow EVERY line that leaves {tag} - pipes (solid) and instrument signal lines (dashed, dotted or solid) -
along the drawn line to the FIRST tagged item it reaches. Lines that merely cross do not connect.
List those first items. Use ONLY tags from the list, spelled exactly as given; leave out lines that leave
the crop without reaching a listed item.

Respond with compact JSON only: {{"connected": ["TAG", "TAG"]}}"""


def _neighbour_votes(img, objects: list[dict], stats: dict) -> dict[tuple[str, str], int]:
    """(a, b) -> how many of the two ends named the other (1 or 2)."""
    from PIL import ImageDraw
    W, H = img.size
    half = NEIGHBOUR_HALF_FRAC * W

    def run(o):
        box = (int(max(0, o["x"] - half)), int(max(0, o["y"] - half)),
               int(min(W, o["x"] + half)), int(min(H, o["y"] + half)))
        x0, y0, x1, y1 = box
        near = [p for p in objects if p is not o and x0 <= p["x"] <= x1 and y0 <= p["y"] <= y1]
        if not near:
            return o, []
        crop = img.crop(box).convert("RGB")
        r = max(12, int(0.009 * W))
        cx, cy = o["x"] - x0, o["y"] - y0
        ImageDraw.Draw(crop).rectangle([cx - r, cy - r, cx + r, cy + r], outline=(230, 0, 0), width=3)
        listing = "\n".join(f"- {p['tag']} at {int((p['x'] - x0) / max(1, x1 - x0) * 1000)},"
                            f"{int((p['y'] - y0) / max(1, y1 - y0) * 1000)}" for p in near)
        prompt = _NEIGHBOUR_PROMPT.format(tag=o["tag"], tags=listing)
        try:
            raw = _vision_call(prompt, _png(crop), 300, model=CONNECT_MODEL) if CONNECT_MODEL \
                else _vision_call(prompt, _png(crop), 300)
        except Exception:
            try:
                raw = _vision_call(prompt, _png(crop), 300)
            except Exception:
                return o, None
        names = {p["tag"] for p in near}
        return o, [str(t).strip() for t in _parse_json(raw).get("connected") or [] if str(t).strip() in names]

    votes: dict[tuple[str, str], int] = {}
    for o, found in _map(run, objects, lambda o: (o, None)):
        stats["calls"] += 1
        if found is None:
            stats["failed_tiles"].append({"pass": "neighbours", "tile": o["tag"], "error": "no answer"})
            continue
        for t in set(found):
            key = (o["tag"], t) if o["tag"] < t else (t, o["tag"])
            votes[key] = votes.get(key, 0) + 1
    return votes


def _graph_rules(edges: list[tuple[str, str, str]], objects: list[dict], stats: dict) -> list[tuple[str, str, str]]:
    """The rules applied to the model's connections: skipped items, cross-loop and
    interlock links, indicator taps, controller-valve links, relays."""
    kinds = {o["tag"]: o["node_kind"] for o in objects}
    added = stats.setdefault("_rule_added", {})
    key = lambda e: (e[0], e[1]) if e[0] < e[1] else (e[1], e[0])

    def track(name, new):
        before = {key(e) for e in edges}
        for e in new:
            if key(e) not in before:
                added[key(e)] = name
        return new

    edges = drop_skipping_edges(edges, {o["tag"]: (o["x"], o["y"]) for o in objects}, stats)
    edges = drop_cross_loop_controller_edges(edges, kinds, stats)
    edges = track("interlock rule", drop_interlock_chains(edges, kinds, stats))
    edges = track("indicator tap rule", add_indicator_taps(edges, kinds, stats))
    edges = track("controller-valve rule", add_controller_valve_links(edges, objects, stats))
    return track("relay rule", route_through_relays(edges, stats))


def combine_neighbours(tile_edges: list[tuple[str, str, str]], votes: dict[tuple[str, str], int],
                       objects: list[dict], mode: str) -> list[tuple[str, str, str]]:
    """The tile pass's links plus the neighbour pass's: those both ends named ("mutual")
    or any named once ("any")."""
    if mode not in ("mutual", "any"):
        return tile_edges
    by_tag = {o["tag"]: o for o in objects}
    have = {(a, b) if a < b else (b, a) for a, b, _k in tile_edges}
    out = list(tile_edges)
    for (a, b), n in sorted(votes.items()):
        if (a, b) in have or (mode == "mutual" and n < 2) or a not in by_tag or b not in by_tag:
            continue
        out.append((a, b, connection_kind(by_tag[a], by_tag[b])))
    return out


def connect_graph(img, objects: list[dict], stats: dict,
                  progress: Callable[[str], None] | None = None) -> list[tuple[str, str, str]]:
    """The connections among the read objects: the connection pass on each
    grid (kept where the grids agree), the graph rules, then the header pass."""
    W, H = img.size
    if CONNECT_EXTENTS:
        _equipment_extents(img, objects, stats)
    grid_tiles = [[{**t, "index": gi * GRID_STRIDE + t["index"], "grid": gi} for t in plan_tiles(W, H, target)]
                  + plan_seam_tiles(W, H, target)
                  for gi, target in enumerate(TILE_GRIDS[:2 if CONNECT_CONSENSUS else 1])]
    pos = {o["tag"]: (o["x"], o["y"], *o["extent"]) if o.get("extent") else (o["x"], o["y"]) for o in objects}
    models = [CONNECT_MODEL or None] + ([CONNECT_SECOND_MODEL] if CONNECT_SECOND_MODEL else [])
    with ThreadPoolExecutor(max_workers=2 * len(models)) as side:    # every grid of every model at once
        futures = [[side.submit(_connect, img, gt, objects, stats, m) for gt in grid_tiles] for m in models]
        per_model, seen_by = [], {}
        for fs in futures:
            seen: dict[tuple[str, str], int] = {}
            per_model.append(consensus_edges([f.result() for f in fs], grid_tiles, pos, seen))
            for key, n in seen.items():
                seen_by[key] = max(seen_by.get(key, 0), n)
    stats["_seen_by"] = seen_by
    if len(per_model) == 1:
        edges = per_model[0]
    else:
        # either model's link is kept; how many models reported it goes to the review queue
        found: dict[tuple[str, str], str] = {}
        votes: dict[tuple[str, str], int] = {}
        for model_edges in per_model:
            for a, b, k in model_edges:
                key = (a, b) if a < b else (b, a)
                found.setdefault(key, k)
                votes[key] = votes.get(key, 0) + 1
        edges = [(a, b, found[(a, b)]) for a, b in sorted(found)]
        stats["_model_votes"] = votes
        stats["connect_models"] = [m or _default_model() for m in models]
    stats["_raw_edges"] = list(edges)                   # before any rule: for offline tuning
    if CONNECT_NEIGHBOURS in ("mutual", "any"):
        votes = _neighbour_votes(img, objects, stats)
        stats["_tile_edges"], stats["_neighbour_votes"] = list(edges), votes
        edges = combine_neighbours(edges, votes, objects, CONNECT_NEIGHBOURS)
    if CONNECT_VERIFY:
        edges = verify_edges(img, edges, objects, stats)
    edges = _graph_rules(edges, objects, stats)
    _tell(progress, "headers")
    if HEADER_PASS:
        # headers and off-sheet flags from their own pass. Run on its own: in parallel
        # with the connection passes its large-model calls timed out under load
        known = {(a, b) if a < b else (b, a) for a, b, _k in edges}
        edges += [e for e in _header_pass(img, objects, stats)
                  if ((e[0], e[1]) if e[0] < e[1] else (e[1], e[0])) not in known]
    return edges


PROGRESS_STAGES = ("read", "verify", "symbols", "connect", "headers")


def _tell(progress: Callable[[str], None] | None, stage: str) -> None:
    if progress is not None:
        try:
            progress(stage)
        except Exception:                      # a display hook must never break a read
            pass


def analyze_uploaded_pid(
    pid: str,
    image_path: str | None = None,
    image_bytes: bytes | None = None,
    *,
    use_ground_truth: bool | None = None,
    use_cache: bool = True,
    verify: bool | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Read an uploaded P&ID with the vision model (tiled, verified, connected).

    `progress(stage)` is told as each pass starts - one of PROGRESS_STAGES -
    so an upload screen can show where a several-minute read has got to.

    Returns {drawing_title, equipment, instruments, tie_ins, lines, loops,
    systems, source, model, stats, warnings} or {"error": "ERROR: ..."}.
    Never returns invented content: on model failure the result is an error.
    """
    f_path, f_bytes, mime = resolve_uploaded_drawing(pid, image_path)
    if image_bytes is not None:
        f_bytes, mime = image_bytes, mime or "image/png"
    if not f_bytes:
        return {"error": f"ERROR: No uploaded P&ID drawing found for project '{pid}'. "
                         "Upload the drawing first."}
    digest = hashlib.sha256(f_bytes).hexdigest()

    if _ground_truth_enabled(use_ground_truth):
        benchmark = resolve_benchmark_ground_truth(pid, f_path)
        if benchmark:
            logger.info(f"[VisionService] Using benchmark ground truth for {pid} (explicitly enabled)")
            return {**benchmark, "source": "ground_truth", "warnings": [
                "Graph loaded from benchmark ground truth, not read from the drawing."]}

    if use_cache:
        cached = load_cached_analysis(pid, digest)
        if cached:
            return cached

    if verify is None:
        verify = os.getenv("BROWNFIELD_VERIFY_TAGS", "1").strip().lower() not in ("0", "false", "no")

    t0 = time.time()
    stats: dict[str, Any] = {"calls": 0, "failed_tiles": [], "dropped_not_a_tag": [],
                             "dropped_unverified": [], "verify_errors": 0,
                             "dropped_edges_unknown_tag": 0}
    try:
        if INPUT_PREP:
            # prepared, checked and gated before any reading call (drawing_input)
            from domain.solution.services import drawing_input as DI
            prep = DI.prepare(f_bytes, mime)
            stats["calls"] += 1 if prep["verdict"] is not None else 0
            stats["input"] = prep["report"]
            if prep["gate"] and prep["gate"][0] == "block":
                return {"error": f"ERROR: the drawing was not digitised: {prep['gate'][1]}. Upload a clearer "
                                 "scan or the original PDF, or check that this is a P&ID.",
                        "input": prep["report"]}
            img, warnings = prep["img"], prep["warnings"]
            if prep["rotated"]:
                # the canvas shows the drawing the positions were read on
                upright = _CACHE_DIR / f"{digest[:16]}_upright.png"
                upright.parent.mkdir(parents=True, exist_ok=True)
                img.save(upright)
                f_path = upright
        else:
            img, warnings = _load_image(f_bytes, mime)
    except Exception as exc:
        return {"error": f"ERROR: could not open the drawing for project '{pid}': {str(exc)[:200]}"}
    W, H = img.size
    # Two reading grids: each misses a different few percent of tags (pid2:
    # the 1500 px grid never read HV-1083 / CK-1059, the 1000 px grid lost
    # the 1032 bubble stack); their union read 98.6% (pid2) and 96-97% (pid18).
    tiles = [{**t, "index": gi * GRID_STRIDE + t["index"], "grid": gi}
             for gi, target in enumerate(TILE_GRIDS) for t in plan_tiles(W, H, target)]
    stats["tiles"] = len(tiles)
    stats["image_px"] = [W, H]
    logger.info(f"[VisionService] Reading {pid} ({W}x{H}) in {len(tiles)} tiles with {VISION_MODEL}")

    _tell(progress, "read")
    readings = _read_tiles(img, tiles, stats)
    if len(stats["failed_tiles"]) > len(tiles) / 2:
        return {"error": "ERROR: the vision model could not read the drawing "
                         f"({len(stats['failed_tiles'])}/{len(tiles)} tile calls failed: "
                         f"{stats['failed_tiles'][0].get('error')}). Nothing was written."}
    if stats["failed_tiles"]:
        warnings.append(f"{len(stats['failed_tiles'])} tile(s) could not be read; "
                        "parts of the drawing may be missing.")

    objects = _merge_readings(readings, tiles, W, stats)
    if verify:
        _tell(progress, "verify")
        objects = _verify(img, objects, W, stats)
    objects = _dedupe_names(_drop_title_callouts(objects, H), W)
    objects = drop_references_and_line_fragments(objects, stats.get("_texts", []), W, stats)
    objects = drop_port_labels(objects, W, stats)
    for old, new in correct_from_loop_pattern(objects, evidence=set(stats.get("dropped_unverified") or [])
                                                  | {r["tag"] for r in readings}):
        warnings.append(f"{new} inferred from loop context (the drawing reads '{old}'); please confirm.")
        stats.setdefault("inferred_tags", []).append({"read": old, "inferred": new})
    texts = stats.pop("_texts", [])
    _tell(progress, "symbols")
    if needs_untagged_pass(objects):
        objects += _untagged_symbols(img, [t for t in tiles if t["grid"] == 0], objects, stats)
    repaired = _repair_orphan_numbers(img, objects, texts, stats)
    if repaired:
        objects += repaired
        stats["repaired_tags"] = [o["tag"] for o in repaired]
    inferred_valves = infer_final_elements(objects, texts, W)
    if inferred_valves:
        objects += inferred_valves
        warnings.append("Unlabelled control valve(s) inferred from their printed annotation and loop: "
                        + ", ".join(o["tag"] for o in inferred_valves) + "; please confirm.")
        stats["inferred_valves"] = [o["tag"] for o in inferred_valves]
    for o in objects:
        if o["node_kind"] not in EQUIPMENT_KINDS | {"tie_in"} and not o.get("inferred"):
            o["kind_detail"] = isa_description(o["tag"]) or o["kind_detail"]
    attach_annotations(objects, texts, W)
    _tell(progress, "connect")
    edges = connect_graph(img, objects, stats, progress)
    lost = sum(1 for f in stats["failed_tiles"] if f.get("pass") == "connect")
    if stats.get("connect_tiles") and lost > stats["connect_tiles"] / 2:
        # a graph without its connections looks complete and is not (pid13 L1 wrote one line)
        return {"error": "ERROR: the vision model could not trace the connections "
                         f"({lost}/{stats['connect_tiles']} tile calls failed: "
                         f"{next(f['error'] for f in stats['failed_tiles'] if f.get('pass') == 'connect')}). "
                         "Nothing was written; please try again."}
    if lost:
        warnings.append(f"{lost} connection tile(s) could not be read; some links may be missing.")
    overview = _overview(img, objects, stats)

    def pos(o):
        return round(o["x"] / W * CANVAS_WIDTH, 1), round(o["y"] / W * CANVAS_WIDTH, 1)

    member_of: dict[str, str] = {}
    for s in overview.get("systems") or []:
        for sub in s["subsystems"]:
            for m in sub["members"]:
                member_of[m] = sub["name"]

    equipment, instruments, tie_ins = [], [], []
    for o in sorted(objects, key=lambda o: (o["y"], o["x"])):
        x, y = pos(o)
        area = member_of.get(o["tag"], "")
        note = "; ".join(o.get("notes") or ([o["note"]] if o.get("note") else []))
        if o["node_kind"] == "tie_in":
            tie_ins.append({"tag": o["tag"], "type": "tie_in", "x": x, "y": y,
                            "description": o["raw"], "snapped": bool(o.get("snapped"))})
        elif o["node_kind"] in EQUIPMENT_KINDS:
            detail = o["kind_detail"]
            desc = (overview.get("equipment_descriptions") or {}).get(o["tag"])
            if desc:
                detail = desc[:1].upper() + desc[1:]
            if note:                            # the drawing names it: "Mixing Tube" wins
                detail = note.split("; ")[0]
                note = "; ".join(x for x in [note, desc] if x)
            equipment.append({"tag": o["tag"], "kind": o["node_kind"], "kind_detail": detail,
                              "area": area, "description": note, "x": x, "y": y,
                              "untagged": bool(o.get("untagged")), "placeholder": bool(o.get("placeholder")),
                              "snapped": bool(o.get("snapped"))})
        else:
            num = o["tag"].split("-", 1)[1] if "-" in o["tag"] else ""
            instruments.append({"tag": o["tag"], "kind": o["node_kind"], "kind_detail": o["kind_detail"],
                                "loop": re.sub(r"[A-Z]$", "", num), "equipment_ref": "",
                                "area": area, "x": x, "y": y, "description": note,
                                "inferred": bool(o.get("inferred")),
                                "untagged": bool(o.get("untagged")), "placeholder": bool(o.get("placeholder")),
                                "snapped": bool(o.get("snapped")), "recovered": bool(o.get("recovered"))})

    by_tag = {o["tag"]: pos(o) for o in objects}
    obj_of = {o["tag"]: o for o in objects}
    lines = [{"line_id": f"L-{i + 1:03d}", "from_tag": a, "to_tag": b,
              "kind": connection_kind(obj_of[a], obj_of[b]) if a in obj_of and b in obj_of else k,
              "size": "", "service": "", "points": [list(by_tag[a]), list(by_tag[b])]}
             for i, (a, b, k) in enumerate(sorted(edges))]
    stats["line_labels_attached"] = attach_line_labels(
        lines, texts, {o["tag"]: (o["x"], o["y"]) for o in objects}, W)

    systems = overview.get("systems") or []
    loops = derive_loops([o["tag"] for o in objects])
    # what the engineer should settle: the last step to 100% (digitise_review)
    from domain.solution.services.digitise_review import build_review_queue
    review = build_review_queue(objects, edges, stats, loops)
    stats["review_items"] = len(review)
    if review:
        warnings.append(f"{len(review)} item(s) need a quick engineer check before the drawing is final "
                        "(see the review queue).")
    stats["seconds"] = round(time.time() - t0, 1)
    stats["dropped_not_a_tag"] = stats["dropped_not_a_tag"][:40]
    analysis = {
        "pid": pid,
        "drawing_title": overview.get("drawing_title") or f"P&ID {pid}",
        "drawing_source": str(f_path) if f_path else "uploaded_bytes",
        # the output frame: x in 0..1000, y in 0..height (the sheet's aspect); the
        # canvas scales the scanned page to exactly this frame so symbols sit on it
        "page": {"width": CANVAS_WIDTH, "height": round(H / W * CANVAS_WIDTH, 1), "image_px": [W, H]},
        "equipment": equipment,
        "instruments": instruments,
        "tie_ins": tie_ins,
        "lines": lines,
        "loops": loops,
        "systems": systems,
        "review": review,
        "source": "vision_tiled",
        "model": VISION_MODEL,
        # working keys ("_...") stay out, except the raw connections kept for offline tuning
        "stats": {k: v for k, v in stats.items() if not k.startswith("_") or k == "_raw_edges"},
        "warnings": warnings,
    }
    logger.info(f"[VisionService] {pid}: {len(equipment)} equipment, {len(instruments)} instruments, "
                f"{len(tie_ins)} tie-ins, {len(lines)} lines in {stats['seconds']}s "
                f"({stats['calls']} model calls)")
    _save_cache(pid, digest, analysis)
    return analysis


def summarize_analysis(analysis: dict) -> str:
    """Compact, agent-sized description of an analysis (fits the tool budget)."""
    if analysis.get("error"):
        return analysis["error"]
    st = analysis.get("stats") or {}
    parts = [
        f"Read '{analysis.get('drawing_title')}' ({analysis.get('source')}): "
        f"{len(analysis.get('equipment') or [])} equipment, "
        f"{len(analysis.get('instruments') or [])} instruments, "
        f"{len(analysis.get('tie_ins') or [])} tie-ins/headers, "
        f"{len(analysis.get('lines') or [])} connections, "
        f"{len(analysis.get('loops') or [])} control loops, "
        f"{len(analysis.get('systems') or [])} system(s).",
        "Equipment: " + ", ".join(e["tag"] for e in analysis.get("equipment") or []) + ".",
        "Headers: " + ", ".join(t["tag"] for t in analysis.get("tie_ins") or []) + ".",
    ]
    if st:
        parts.append(f"{st.get('tiles')} tiles, {st.get('calls')} model calls, {st.get('seconds')}s; "
                     f"{len(st.get('dropped_unverified') or [])} unverified reading(s) discarded.")
    for w in analysis.get("warnings") or []:
        parts.append(f"WARNING: {w}")
    return " ".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Public: rebuild
# ═══════════════════════════════════════════════════════════════════════════

def _decluster_coordinates(nodes: list[dict[str, Any]], min_dist: float = 14.0) -> dict[str, tuple[float, float]]:
    """Nudge nodes that sit on top of each other apart. min_dist is in the
    1000-wide output frame; the old 110 scattered dense instrument stacks
    (FIC/FT/FE bubbles ~15 units apart) across the sheet. A node marked
    "snapped" (placed exactly, in analyses cached before the digitiser became
    LLM-only) never moves; its neighbour moves the whole distance instead."""
    positions: dict[str, list[float]] = {}
    fixed = {n["tag"] for n in nodes if n.get("snapped")}
    for n in nodes:
        positions[n["tag"]] = [float(n.get("x") or 300.0), float(n.get("y") or 300.0)]

    for _ in range(12):
        moved = False
        tags = list(positions.keys())
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                p1, p2 = positions[tags[i]], positions[tags[j]]
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                dist = (dx * dx + dy * dy) ** 0.5
                f1, f2 = tags[i] in fixed, tags[j] in fixed
                if dist < min_dist and not (f1 and f2):
                    moved = True
                    if dist == 0:
                        dx, dy, dist = 1.0, 1.0, 1.414
                    share1 = 0.0 if f1 else (1.0 if f2 else 0.5)
                    overlap = min_dist - dist
                    nx, ny = (dx / dist) * overlap, (dy / dist) * overlap
                    p1[0] -= nx * share1; p1[1] -= ny * share1
                    p2[0] += nx * (1 - share1); p2[1] += ny * (1 - share1)
        if not moved:
            break
    return {tag: (round(p[0], 1), round(p[1], 1)) for tag, p in positions.items()}


def _vision_flags(n: dict) -> dict:
    """What the canvas must show about how a symbol was obtained."""
    return {"inferred": bool(n.get("inferred")), "untagged": bool(n.get("untagged")),
            "placeholder": bool(n.get("placeholder")), "snapped": bool(n.get("snapped")),
            "recovered": bool(n.get("recovered"))}


def _page_frame(analysis: dict) -> dict:
    """The output frame of an older analysis that did not record it: the
    drawing's own aspect when the file is at hand, else the extent read."""
    src = analysis.get("drawing_source") or ""
    try:
        from PIL import Image
        with Image.open(src) as im:
            W, H = im.size
        return {"width": CANVAS_WIDTH, "height": round(H / W * CANVAS_WIDTH, 1), "image_px": [W, H]}
    except Exception:
        ys = [n.get("y") or 0 for g in ("equipment", "instruments", "tie_ins") for n in analysis.get(g) or []]
        return {"width": CANVAS_WIDTH, "height": round(max(ys, default=700) * 1.05, 1), "image_px": None}


def rebuild_digital_pid(
    pid: str,
    analysis: dict[str, Any] | None = None,
    user_id: int | None = 1,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Persist an analysis as the project's digital P&ID graph.

    With no analysis given, the cached analysis of the same drawing is used;
    the model only runs if there is none. Edges whose endpoints were not
    read as nodes are skipped (and counted) rather than stored dangling.
    """
    if analysis is None or "equipment" not in analysis:
        analysis = analyze_uploaded_pid(pid)
        if "error" in analysis:
            return analysis

    from adapters.db import get_db, init_db
    init_db()
    db = get_db()

    drawing_title = analysis.get("drawing_title") or f"P&ID {pid} Digitized"
    drawing_src = analysis.get("drawing_source") or "uploaded_pid.png"

    db.execute(
        "INSERT INTO projects (id, title, company, process_type, created, plant_name, revision, status, extraction_locked) "
        "VALUES (?, ?, 'EngineeringStudio', 'Continuous', datetime('now'), ?, 1, 'digitised', 1) "
        "ON CONFLICT(id) DO UPDATE SET status='digitised', extraction_locked=1, revision=COALESCE(revision, 1)+1",
        (pid, drawing_title, drawing_title)
    )
    try:
        if not db.execute("SELECT 1 FROM sources WHERE pid=? AND filename=?", (pid, drawing_src)).fetchone():
            db.execute("INSERT INTO sources (pid, filename, uploaded, cached) VALUES (?, ?, datetime('now'), 1)",
                       (pid, drawing_src))
    except Exception as exc:
        logger.debug(f"[VisionService] Could not insert source: {exc}")

    # Clear the previous extraction (authored rows are kept)
    for sql in (
        "DELETE FROM nodes WHERE pid=? AND (origin='extracted' OR origin IS NULL)",
        "DELETE FROM edges WHERE pid=? AND (origin='extracted' OR origin IS NULL)",
        "DELETE FROM canvas_positions WHERE pid=?",
        "DELETE FROM geometry_lines WHERE pid=?",
        "DELETE FROM loops WHERE pid=?",
        "DELETE FROM connections WHERE pid=? AND id LIKE 'e_vis_%'",
        "DELETE FROM equipment WHERE pid=? AND extra_json LIKE '%brownfield_vision%'",
        "DELETE FROM instruments WHERE pid=? AND extra_json LIKE '%brownfield_vision%'",
    ):
        try:
            db.execute(sql, (pid,))
        except Exception as exc:
            logger.debug(f"[VisionService] Cleanup notice ({sql[:40]}...): {exc}")

    equipment_list = analysis.get("equipment") or []
    instruments_list = analysis.get("instruments") or []
    tie_ins = analysis.get("tie_ins") or []

    raw_nodes = []
    for group in (equipment_list, instruments_list, tie_ins):
        for n in group:
            t = str(n.get("tag") or "").strip()
            if t:
                raw_nodes.append({"tag": t, "x": n.get("x", 300.0), "y": n.get("y", 300.0),
                                  "snapped": bool(n.get("snapped"))})
    resolved_positions = _decluster_coordinates(raw_nodes)

    inserted_nodes: list[str] = []

    def _insert_node(tag, kind, kind_detail, area, extra):
        x, y = resolved_positions.get(tag, (300.0, 300.0))
        db.execute(
            "INSERT OR REPLACE INTO nodes (id, pid, kind, kind_detail, label, area, x, y, extra_json, origin) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'extracted')",
            (tag, pid, kind, kind_detail, tag, area, x, y, json.dumps(extra)))
        db.execute("INSERT OR REPLACE INTO canvas_positions (pid, node_id, x, y) VALUES (?, ?, ?, ?)",
                   (pid, tag, x, y))
        inserted_nodes.append(tag)

    source_label = analysis.get("source") or "brownfield_vision"
    for eq in equipment_list:
        tag = str(eq.get("tag") or "").strip()
        if not tag or tag in inserted_nodes:
            continue
        kind = eq.get("kind") or "vessel"
        kind_detail = eq.get("kind_detail") or kind.title()
        area = eq.get("area") or "Process Area"
        extra = {"description": eq.get("description", ""), "origin": "extracted",
                 "source": "brownfield_vision", "reader": source_label, "spec_status": "nameplate",
                 **_vision_flags(eq)}
        _insert_node(tag, kind, kind_detail, area, extra)
        db.execute("INSERT OR REPLACE INTO equipment (tag, pid, area, kind_detail, type, extra_json) "
                   "VALUES (?, ?, ?, ?, ?, ?)", (tag, pid, area, kind_detail, kind, json.dumps(extra)))

    for inst in instruments_list:
        tag = str(inst.get("tag") or "").strip()
        if not tag or tag in inserted_nodes:
            continue
        kind = inst.get("kind") or "instrument"
        kind_detail = inst.get("kind_detail") or kind.title()
        area = inst.get("area") or "Instrumentation"
        extra = {"loop": inst.get("loop", ""), "equipment_ref": inst.get("equipment_ref", ""),
                 "origin": "extracted", "source": "brownfield_vision", "reader": source_label,
                 "spec_status": "nameplate", "description": inst.get("description", ""),
                 **_vision_flags(inst)}
        _insert_node(tag, kind, kind_detail, area, extra)
        db.execute("INSERT OR REPLACE INTO instruments (tag, pid, area, kind_detail, type, equipment_ref, extra_json) "
                   "VALUES (?, ?, ?, ?, ?, ?, ?)",
                   (tag, pid, area, kind_detail, kind, inst.get("equipment_ref", ""), json.dumps(extra)))

    for tp in tie_ins:
        tag = str(tp.get("tag") or "").strip()
        if not tag or tag in inserted_nodes:
            continue
        extra = {"description": tp.get("description", ""), "origin": "extracted",
                 "source": "brownfield_vision", "reader": source_label, **_vision_flags(tp)}
        _insert_node(tag, "tie_in", "Tie-In / Header", "Tie-In Zone", extra)

    node_set = set(inserted_nodes)
    inserted_edges: list[str] = []
    skipped_edges = 0
    for idx, line in enumerate(analysis.get("lines") or []):
        f_tag = str(line.get("from_tag") or "").strip()
        t_tag = str(line.get("to_tag") or "").strip()
        if not f_tag or not t_tag:
            continue
        if f_tag not in node_set or t_tag not in node_set:
            skipped_edges += 1
            continue
        line_id = line.get("line_id") or f"L-{idx + 1:03d}"
        kind = line.get("kind") or "process"
        pts = line.get("points") or []
        extra = {"line_id": line_id, "size": line.get("size", ""), "service": line.get("service", ""),
                 "points": pts, "origin": "extracted", "source": "brownfield_vision",
                 **{k: line[k] for k in ("spec", "fluid", "note", "printed_line_no") if line.get(k)}}
        db.execute("INSERT INTO edges (pid, from_id, to_id, kind, label, extra_json, origin) "
                   "VALUES (?, ?, ?, ?, ?, ?, 'extracted')",
                   (pid, f_tag, t_tag, kind, line_id, json.dumps(extra)))
        db.execute("INSERT OR REPLACE INTO connections (id, pid, from_tag, to_tag, type, extra_json) "
                   "VALUES (?, ?, ?, ?, ?, ?)",
                   (f"e_vis_{idx + 1}", pid, f_tag, t_tag, kind, json.dumps(extra)))
        if pts:
            db.execute("INSERT OR REPLACE INTO geometry_lines (pid, line_id, type, points_json) VALUES (?, ?, ?, ?)",
                       (pid, f"gl_{idx + 1}", kind, json.dumps(pts)))
        inserted_edges.append(f"{f_tag} -> {t_tag}")

    loops_list = [lp for lp in analysis.get("loops") or []
                  if any(m in node_set for m in lp.get("members") or [])]
    for lp in loops_list:
        lid = str(lp.get("loop_id") or "").strip()
        if lid:
            db.execute("INSERT OR REPLACE INTO loops (loop_id, pid, loop_json) VALUES (?, ?, ?)",
                       (lid, pid, json.dumps(lp)))

    # Hierarchy: subsystems may be plain names or {"name", "members"}
    systems_list = analysis.get("systems") or []
    subsystem_ids: dict[str, int] = {}
    member_to_sub: dict[str, int] = {}
    for sys_item in systems_list:
        sys_name = sys_item.get("name") or "Main Process System"
        try:
            db.execute("INSERT OR IGNORE INTO hierarchy (pid, parent_id, level, name, code) VALUES (?, 0, 'system', ?, ?)",
                       (pid, sys_name, sys_name[:6].upper()))
            sys_row = db.execute("SELECT id FROM hierarchy WHERE pid=? AND name=? AND level='system'",
                                 (pid, sys_name)).fetchone()
            parent_id = sys_row[0] if sys_row else 0
            for sub in sys_item.get("subsystems") or []:
                sub_name = sub if isinstance(sub, str) else sub.get("name")
                if not sub_name:
                    continue
                db.execute("INSERT OR IGNORE INTO hierarchy (pid, parent_id, level, name, code) VALUES (?, ?, 'subsystem', ?, ?)",
                           (pid, parent_id, sub_name, sub_name[:6].upper()))
                sub_row = db.execute("SELECT id FROM hierarchy WHERE pid=? AND name=? AND level='subsystem'",
                                     (pid, sub_name)).fetchone()
                if sub_row:
                    subsystem_ids[sub_name.lower()] = sub_row[0]
                    if isinstance(sub, dict):
                        for m in sub.get("members") or []:
                            member_to_sub[m] = sub_row[0]
        except Exception as exc:
            logger.debug(f"[VisionService] Hierarchy insertion notice: {exc}")

    assigned = 0
    try:
        db.execute("DELETE FROM node_hierarchy WHERE pid=?", (pid,))
        for node_id in inserted_nodes:
            hid = member_to_sub.get(node_id)
            if hid is None:
                row = db.execute("SELECT area FROM nodes WHERE pid=? AND id=?", (pid, node_id)).fetchone()
                area = ((row[0] if row else "") or "").lower()
                hid = subsystem_ids.get(area)
            if hid is not None:
                db.execute("INSERT OR REPLACE INTO node_hierarchy (pid, node_id, hierarchy_id) VALUES (?, ?, ?)",
                           (pid, node_id, hid))
                assigned += 1
    except Exception as exc:
        logger.debug(f"[VisionService] node_hierarchy link warning: {exc}")

    # The sheet the positions are measured on, so the canvas can lay the scanned
    # page under the symbols at the same scale.
    page = analysis.get("page") or _page_frame(analysis)
    try:
        db.execute("CREATE TABLE IF NOT EXISTS pid_drawing_meta (pid TEXT PRIMARY KEY, page_w REAL, "
                   "page_h REAL, image_path TEXT, meta_json TEXT)")
        db.execute("INSERT OR REPLACE INTO pid_drawing_meta (pid, page_w, page_h, image_path, meta_json) "
                   "VALUES (?, ?, ?, ?, ?)",
                   (pid, page.get("width"), page.get("height"), analysis.get("drawing_source") or "",
                    json.dumps({"image_px": page.get("image_px"), "warnings": analysis.get("warnings") or [],
                                "model": analysis.get("model"), "source": source_label})))
    except Exception as exc:
        logger.debug(f"[VisionService] drawing meta notice: {exc}")

    db.commit()

    # the review queue next to the graph; decisions taken on an earlier read of the
    # same drawing are applied again (rejected items stay removed, renames stay)
    review_open = 0
    try:
        from domain.solution.services import digitise_review as DR
        review_open = DR.store_queue(pid, analysis.get("review") or [])["open"]
        DR.reapply_decisions(pid)
    except Exception as exc:
        logger.warning(f"[VisionService] review queue not stored: {exc}")

    try:
        from common.infra.repositories.pid_graph_repository import PIDGraphRepository
        PIDGraphRepository().save(user_id=user_id or 1, session_id=session_id or pid, graph={
            "pid": pid, "session_id": session_id or pid, "title": drawing_title,
            "digitised": True, "status": "digitised",
            "nodes": [{"id": n, "label": n, "origin": "extracted"} for n in inserted_nodes],
            "edges": [{"line": e, "origin": "extracted"} for e in inserted_edges],
            "equipment": equipment_list, "instruments": instruments_list, "loops": loops_list,
            "tie_ins": tie_ins, "systems": systems_list,
            "summary": f"Digitized drawing with {len(inserted_nodes)} nodes, {len(inserted_edges)} lines, "
                       f"{len(loops_list)} loops.",
        })
    except Exception as exc:
        logger.warning(f"[VisionService] MongoDB repository persistence warning: {exc}")

    unassigned = len(inserted_nodes) - assigned
    summary_str = (
        f"Digitised P&ID '{pid}' from the drawing ({source_label}): {len(inserted_nodes)} nodes "
        f"({len(equipment_list)} equipment, {len(instruments_list)} instruments, {len(tie_ins)} headers), "
        f"{len(inserted_edges)} connections, {len(loops_list)} control loops."
    )
    if skipped_edges:
        summary_str += f" {skipped_edges} connection(s) skipped: an end was not read as a node."
    if unassigned:
        summary_str += f" {unassigned} node(s) not assigned to a subsystem."
    for w in analysis.get("warnings") or []:
        summary_str += f" WARNING: {w}"
    logger.info(f"[VisionService] {summary_str}")

    accuracy_score = None
    try:
        from domain.solution.services.pid_accuracy_service import save_accuracy_evaluation
        acc_rec = save_accuracy_evaluation(
            pid=pid, agent_type="brownfield_vision",
            user_message="Rebuild digital P&ID from drawing scan",
            metadata={"nodes_count": len(inserted_nodes), "edges_count": len(inserted_edges),
                      "equipment_count": len(equipment_list), "reader": source_label})
        accuracy_score = acc_rec.get("accuracy_score")
    except Exception as exc:
        logger.warning(f"[VisionService] Local accuracy metrics saving notice: {exc}")

    return {
        "status": "success",
        "digitised": True,
        "pid": pid,
        "source": source_label,
        "accuracy_score": accuracy_score,
        "nodes_rebuilt": len(inserted_nodes),
        "edges_rebuilt": len(inserted_edges),
        "edges_skipped": skipped_edges,
        "equipment_count": len(equipment_list),
        "instruments_count": len(instruments_list),
        "loops_count": len(loops_list),
        "tie_ins_count": len(tie_ins),
        "review_open": review_open,
        "summary": summary_str + (f" {review_open} item(s) await the engineer's review." if review_open else ""),
    }
