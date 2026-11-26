# EngineeringStudio — Claude Code Guide
# Read RULES.md alongside this file.

---

## What this is
Flask P&ID digitisation tool. Reads scanned P&ID PDFs via Claude API,
extracts equipment/instruments with positions, renders interactive SVG canvas,
exports to VIDS / YMPL / SVG / DXF / DEXPI.

## Run
```
cd C:\standard\studio
python3 main.py
# http://localhost:8000
```

## Key files
```
main.py                        Flask routes (all backend)
templates/index.html           Studio UI (upload, review, bulk accept, export)
templates/canvas.html          Interactive P&ID canvas (per-page, compare+edit)
adapters/engine.py             Type normalizer, internal model builder
adapters/ympl_convert.py       enableSim export
adapters/svg_pid.py            Server-side ISA-5.1 SVG generator
schemas/internal_schema.yaml   Internal model definition
skills/core/p_and_id/SKILL.md  Claude vision prompt
RULES.md                       Architecture rules (read before coding)
```

## Data flow
```
PDF upload -> SHA256 hash -> cache check
  cache hit  -> instant return
  cache miss -> Pass 1 (Sonnet streaming, 64k tokens)
                  nodes with x,y,drawing,area per page
             -> Pass 2 (Haiku, batches of 30)
                  instrument params cached per batch
             -> Save to .espx + project.json + source_docs/
             -> Canvas renders at extracted positions
             -> Engineer drags/edits -> saved to canvas.json
             -> Export: VIDS / YMPL / SVG
```

## Project folder
```
EngineeringHub/projects/<pid>/
  <pid>.espx          Main data: nodes, edges, studio data
  project.json        Manifest
  review.json         Engineer decisions
  canvas.json         Node positions + verification flags
  source_docs/        PDFs served to canvas
  cache/              pass0, pass1, bN_pass2 JSON files
  exports/            vids.yaml, .ympl, _pid.svg
```

## Hub path
Default: C:\standard\EngineeringHub (repo root / EngineeringHub)
Override: ENGINEERING_HUB in .env

## Models
MODEL_VISION  = claude-sonnet-4-6     (Pass 1, streaming)
MODEL_EXTRACT = claude-haiku-4-5-20251001  (Pass 2 batches)

## Detection: pure LLM, no ML fallback

Every symbol, tag and pipe run is read by a vision LLM. No trained model
participates in detection: no YOLOv8, no U-Net, no RapidOCR, and no fallback to
any of them. If the configured provider cannot accept images, detection FAILS
LOUDLY rather than quietly switching engines.

- One resolver: `services/detection_router.py`. `main.py`, `api/detect.py`,
  `extraction_cli/image.py` and the three extraction agents all go through it.
  Never import a detection service directly.
- `STUDIO_DETECTION_ENGINE` is still read, but `llm` is the only accepted
  value. A leftover `cv` or `auto` is logged and ignored, never honoured.
- Legacy trained model files (`detection_service.py`, `text_detection_service.py`,
  `line_detection_service.py`, `_ml_disabled.py`) are completely removed. Pure
  classical geometry (tiling, non-max suppression, box merging, line grouping, leader-line
  filtering, snapping) is cleanly isolated in `services/geometry/`, which the
  vision-LLM detectors reuse without any ML dependencies.
- `torch`, `torchvision`, `ultralytics` and `rapidocr-onnxruntime` are NOT
  dependencies, and the Dockerfile no longer installs PyTorch. **No model
  weights are needed or used.**
- OpenCV and NumPy remain, for cutting tiles, measuring ink density and encoding
  PNGs. Classical image manipulation is not machine learning.

`GET /api/agent/health` reports `detection_engine`, `provider_vision` and
`no_ml_loaded`, the last being a live check that no trained-model package has
been imported into the process.

## Extraction pipeline switch

`STUDIO_EXTRACTION_ENGINE` (or the `extraction_engine` setting) picks which
orchestration the desktop app runs: `classic` (default, `extract_cli.py`) or
`agentic` (`run_agentic.py`, LangGraph multi-agent). This is independent of
detection -- both pipelines use the vision-LLM detectors.

Detection speed and accuracy settings:
- `STUDIO_TILE_CONCURRENCY` (default 4, clamped 1–16): parallel tile calls in
  the symbol and line detectors. Results aggregate in tile order, and a failed
  tile is skipped rather than failing the page (`services/tile_runner.py`).
- `STUDIO_ZOOM_REFINE` (default on): detections scoring below 0.80 are re-asked
  on a tight crop to confirm them and tighten their box (max 60 per page).
- `STUDIO_FLOW_ANNOTATIONS` (default on): one extra tiled vision pass per page
  reads flow arrows and electric heat tracing into the saved geometry. The
  connectivity export uses the arrows for flow direction and exports the heat
  tracing. The test suite turns it off in `tests/conftest.py`.
- The Anthropic adapter marks the system prompt for prompt caching and never
  sends an assistant prefill to models that reject one (Opus 4.6+, Sonnet 4.6+,
  Fable, Opus 5); cost accounting includes cache writes and reads.

## Brownfield retrofit and exports

Digitise a P&ID, retrofit it through the brownfield Describe agent, and export.
Design and status: `docs/BROWNFIELD_IMPLEMENTATION_PLAN.md`; agent details:
`agents/README.md` → "Brownfield retrofit".

- Hierarchy site › plant › unit › area › system › subsystem: `services/hierarchy.py`,
  tables `hierarchy` and `node_hierarchy`.
- Instrument packages (pressure, temperature, flow, level, optional control
  tail) are built by code, not by the model: `services/instrument_packages.py`.
- Specifications are never invented (`services/asset_specs.py`): MongoDB asset
  inventory when `STUDIO_ASSET_INVENTORY=mongodb`, otherwise what the engineer
  stated, otherwise `spec_status: "unspecified"`.
- Authored rows carry `extra_json.origin = "authored"` and survive re-extraction;
  database triggers mirror that marker into `nodes.origin` / `edges.origin`.
- Before a retrofit runs, `agents/describe/services/subsystem_gate.py` asks
  which subsystem it belongs to when that is ambiguous or unstated.
- Geometry (page sizes, line polylines, junctions) is persisted by both
  extraction pipelines: `services/geometry_store.py`.
- Connectivity graph JSON: `adapters/connectivity_export.py`, schema 2.0.0
  (`schemas/connectivity_graph_2_0_0.schema.json`) or 2.1.0 with hierarchy.
- YMPL: `adapters/ympl_export.py` is the single writer for Flask, the desktop
  (via `export_ympl_cli.py`) and the MCP server.
- Both exports regenerate after an agent turn that wrote to the graph, unless
  `STUDIO_AUTO_EXPORT=off`.
- **DB schema lives in two files**, `adapters/db.py` and
  `frontend/src-tauri/src/database/schema.rs`. Change both;
  `tests/test_schema_parity.py` fails on any difference.

## Detection benchmark

`benchmarks/` scores extraction against ground-truth connectivity graphs in
`../fixtures/ground_truth/` (tag P/R/F1, type accuracy, box IoU, connection F1
with junction chains collapsed). `pid18.json` is derived from
`fixtures/connectivity_graph 18.json` and is **not yet verified by hand**.
```
python benchmarks/run_benchmark.py --dry-run                 # validates, no model calls
python benchmarks/run_benchmark.py --limit 1 --confirm-cost  # live: calls the vision model
```
Live runs refuse to start without `--confirm-cost`. Results land in
`benchmarks/results/<timestamp>/` (gitignored: the throwaway hubs there hold
copied provider settings).

## All API routes
GET  /
GET  /canvas/<pid>
POST /api/projects
GET  /api/projects
GET  /api/projects/<pid>
DELETE /api/projects/<pid>
POST /api/projects/<pid>/parse/text
POST /api/projects/<pid>/parse/image
GET  /api/projects/<pid>/export/vids
GET  /api/projects/<pid>/export/ympl
GET  /api/projects/<pid>/export/connectivity   (?schema=2.1.0 for hierarchy)
GET  /api/projects/<pid>/export/svg
GET  /api/projects/<pid>/export/dxf
GET  /api/projects/<pid>/export/markdown
GET  /api/projects/<pid>/canvas
POST /api/projects/<pid>/canvas
GET  /api/projects/<pid>/source/<file>
POST /api/projects/<pid>/review/<tag>
GET  /api/projects/<pid>/review
GET  /api/projects/<pid>/manifest
POST /api/projects/<pid>/parse/notes
GET  /api/hub

## Canvas
Left: embedded PDF from source_docs/
Right: SVG canvas with ISA-5.1 symbols at Claude-extracted x,y positions
Drag nodes to adjust position - saved to canvas.json
Click node - edit panel (tag, kind, range, units, verified checkbox)
Drawing selector groups by drawing number from Pass 1 title block reading
Export SVG downloads and saves to exports/

## Connection types (see RULES.md for full spec)
Currently rendered: stream (solid), signal (dashed), recycle (blue dashed)
Need to add: pneumatic (dot-dash), electrical (dashed gold), hydraulic (double dashed)
Add to EDGE_STYLES in canvas.html and EDGE_COLORS in svg_pid.py

## Process Reconstruction Skills

Location: `studio/skills/reconstruction/`

These files define how PlantSketch renders P&ID diagrams:
- `process-reconstruction.md` — gaps analysis, layout YAML, rendering rules
- `process-reconstruction-skill.md` — equipment patterns, valve placement, prompt templates
- `process-reconstruction-v2.md` — updated gap analysis with CTP project findings

ALWAYS read these files before:
- Modifying canvas rendering code
- Changing the extraction prompt
- Adding layout or positioning logic
- Working on ISA symbol rendering

Key rules from the skills:
- Equipment on backbone (y=400) left-to-right
- Instruments 120px below parent equipment
- Control valves inline on backbone
- Utilities in separate band 600px below
- Process pipes: solid horizontal-first routing
- Signal lines: dashed vertical-only routing
- ISA symbols: bowties for valves, circles for instruments

---

## New Extraction Pipeline (May 2026)

Files: `page_splitter.py`, `prompts.py`, `tag_validator.py`, `extract_page.py`,
`extract_full_test.py`, `import_extraction.py`

Architecture change — one Sonnet call per PDF page instead of one multi-page batch:
```
PDF → page_splitter.py → page_1.png … page_N.png
                                ↓
              extract_page.py (Sonnet, PASS1_SINGLE_PAGE prompt)
                                ↓
              tag_validator.py (ghost tag rejection, off_page passthrough)
                                ↓
              import_extraction.py → studio.db (nodes, edges, instruments, equipment)
```

Results vs old approach on CTP (19 drawings):
| Metric          | Old multi-page | New per-page |
|-----------------|---------------|--------------|
| Valid nodes     | 857 (many ghosts) | 364 (clean) |
| Edges           | 162           | 289 (+78%)   |
| Ghost tags      | ~500          | 3            |
| Edge/node ratio | 0.17          | 0.79         |
| Input tokens    | 64 000        | 51 205       |

Key changes:
- `prompts.py` — `PASS1_SINGLE_PAGE` constant: explicit pipe-tracing instructions,
  ghost-tag blacklist, equipment_ref extraction, off-page connector handling
- `tag_validator.py` — rejects bare ISA letters, low-confidence tags; passes `off_page_*`
- Pass 2.5 (Haiku pipe runs) eliminated — pipe topology now from Pass 1 per-page
- `extract_cli.py` — standalone CLI that Tauri desktop spawns for streaming extraction

---

## Next tasks
1. pneumatic/electrical/hydraulic line styles
2. Symbol library loader from symbols/ folder
3. Notes/legend parser - POST /api/projects/<pid>/parse/notes
4. Per-page canvas -> combined full-plant view
5. Add connection by clicking two nodes
6. Parallel Pass 2 batches
7. DXF export (ezdxf)
8. DEXPI XML (ISO 15926)
9. Markdown + Mermaid export

## Quick test
python3 -c "
import sys,os; sys.path.insert(0,'.')
os.environ['ANTHROPIC_API_KEY']='test'
os.environ['ENGINEERING_HUB']='/tmp/t'
from main import app
print(len(list(app.url_map.iter_rules())),'routes OK')
"
