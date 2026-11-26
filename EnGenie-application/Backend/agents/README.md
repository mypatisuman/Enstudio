# Agentic Application Layer

LangGraph-based multi-agent system for enSTUDIO, structured after the
`domain/` reference architecture: one package per workflow, each with
`agents/` (node logic), `workflows/` (graph wiring), `prompts/`
(co-located `.md` files + `catalog.py` constants), `state.py`,
`schemas.py`, and `health.py`.

## Structure

```
agents/
  toolkit.py        controller runner (metrics in, one JSON decision out,
                    enumerated actions, rules fallback), JSON armor, IoU
  streaming.py      NDJSON progress bridge (+ numeric progress contract)
  checkpoints.py    SqliteSaver on langgraph.db (never studio.db)
  retry.py          @retryable_node(max_attempts, label, on_exhausted)

  orchestrator/     application entry: router agent -> workflow dispatch
    agents/router_agent.py        route_request()
    workflows/app_workflow.py     run_app_request()  — unified envelope
    workflows/health.py           check_app_health() — aggregated report
    prompts/app_router.md

  extraction/       drawing -> graph (9 dedicated agents)
    agents/         symbol, text, line, cv_coordination, relationship,
                    harness (LLM A verify + LLM B audit), inference,
                    grid_layout (row/column tile grid — see below),
                    orchestration (intake/cache/warmup/merge/finalize)
    workflows/extraction_workflow.py   build_extraction_workflow(),
                                       run_extraction_agentic()
    prompts/        10 .md files + catalog.py
    state.py  schemas.py  health.py

  describe/         description -> graph edits (router + holistic gate +
                    5 dedicated agents)
    agents/         router, holistic (disambiguation gate), query,
                    authoring, update, deletion, validation
    base.py         shared bounded tool-loop engine (infrastructure)
    services/repository.py    data-access layer (shared nodes/edges tables)
    services/grid_service.py  Describe-side bridge to the tile grid +
                              find_adjacent_cell_pairs() (disambiguation)
    workflows/describe_workflow.py   run_describe_turn(),
                                     resolve_describe_turn()
    prompts/        7 .md files + catalog.py
    state.py  schemas.py  health.py  api.py (Flask blueprint)
```

## Conventions

- **Agent = one module + node function(s).** Sub-functions are private
  helpers in the same module. An agent's tool ownership is structural:
  a Describe specialist physically cannot call a tool outside its
  registry.
- **Prompt = one co-located `.md` file**, loaded into a named constant in
  the workflow's `prompts/catalog.py`. The loader/filler lives once in
  `agents/prompts/` (deliberately not duplicated per workflow).
- **Workflows wire, agents work.** Graph assembly never lives with node
  logic.
- **Controllers see metrics, never images.** All vision goes through the
  two proven prompts in `studio/prompts.py` (`CV_VERIFY_PROMPT`,
  `CV_CONNECTIONS_PROMPT`), reused verbatim via
  `extraction_cli/llm_verification.py`.
- **Every controller has a coded deterministic fallback** — an LLM outage
  degrades to rules, never blocks. Every retry is bounded (QC loops: 2
  per stage; exception retries: `@retryable_node`, with a per-node
  `on_exhausted` degradation policy).
- **Structured outputs pass a schema wall** (`schemas.py`, pydantic v2,
  `extra="ignore"`): malformed controller decisions fall back to rules;
  LLM results are normalized with `ensure_compliant()` (never raises).
- **Human gates**: extraction defers to the Review screen and the
  `proposals` table (persisted by `inference_agent.py`, `review_state`
  defaults to `inferred`); describe deletion pauses on a checkpointed
  `interrupt()` until the engineer confirms — the interrupt payload
  carries `resolved` (the Holistic gate's disambiguated node id, when a
  duplicated tag was involved) so the confirmation targets one specific
  occurrence, never an arbitrary match.
- **Streaming**: NDJSON lines on stdout (same contract as the classic
  `extract_cli.py`) + LangGraph custom stream + numeric `progress`
  percentages (`streaming.STAGE_PROGRESS`). **Stage names are not free
  to choose**: `src-tauri/src/commands/extraction.rs` (usage/cost
  persistence) and `src/state/ExtractionContext.tsx` (the Ingest
  screen's "complete" state) both hardcode a literal string match on
  `"done"` for success and `"error"` for failure — using anything else
  for the terminal stage (e.g. the earlier `"finish"`) makes every
  successful run look like a crash the moment this pipeline is wired
  into the desktop app, even though nothing throws. Fixed once already
  (`orchestration.finalize()` / `extraction_workflow.py`'s exception
  handler both emit `"done"`/`"error"` now) — if you add a new terminal
  path, match one of those two names, not a new one.

## Multi-page extraction, cache, usage, conventions, manifest (closed)

All six extraction gaps identified against the rest of the app (E1–E6)
are closed:

- **E1 — multi-page fan-out**: `orchestration.intake()` renders every
  PDF page (`extraction_cli/pdf.render_pdf_pages_to_png()`, same
  per-page adaptive scaling rule as the old single-page
  `_render_pdf_to_png`). `extraction_workflow.py` compiles the classic
  symbol→text/line→llm_a→cv_consolidation→relationship→llm_b chain once
  as `build_page_pipeline()`, then fans out with LangGraph's `Send` API
  — one invocation per page, each seeing `page_paths` narrowed to its
  own page so every existing agent's `page_paths[0]` assumption still
  holds unmodified. Results are namespaced with a `"p{i}_"` id prefix
  (`_namespace_page_results`) before `merge_results` combines them
  (`orchestration._collect_pages`) — a single-page run (N=1) is the
  degenerate case and produces the same shape as before this change,
  just with a `p0_` prefix. See `extraction_multipage_plan.md` for the
  full design rationale and `tests/test_extraction_multipage.py`.
- **E4 — cache + usage**: `cache_check`/`merge_results` now correctly
  call the DB-backed `CacheStore.get(pid, key)`/`.put(pid, key, ...)`
  (previously `cache_check` called `store.get(key)` — missing the
  required `pid` arg — which always raised `TypeError` and was silently
  swallowed as a permanent cache miss). `harness_agent.py`'s
  `llm_a_node`/`llm_b_node` now correctly unpack
  `_call_llm_verification`/`_call_llm_connections`'s `(result, resp)`
  tuple return (previously treated as a bare dict, which would have
  raised `TypeError: 'tuple' object is not a mapping` on any real,
  non-stubbed run) and record token/cost usage into `state["usage"]`.
  `finalize()` sums `usage` into flat `tokens_in`/`tokens_out`/`cost_usd`
  fields on the `"done"` NDJSON line, matching what
  `src-tauri/src/commands/extraction.rs` already reads for the
  UsageScreen. See `tests/test_orchestration_cache.py`,
  `tests/test_harness_agent.py`.
- **E5 — company conventions**: `harness_agent._conventions_text()`
  resolves the project's `CompanyConventions.as_skill_text()` (same
  lookup as the classic pipeline's `extraction_controller._get_conventions`)
  and threads it into both LLM A and LLM B calls via a new optional
  `conventions_text` kwarg on `extraction_cli/llm_verification.py`'s
  `_call_llm_verification`/`_call_llm_connections` (default `''`, so the
  classic pipeline's existing call sites are unaffected). See
  `tests/test_harness_agent.py`.
- **E6 — manifest tracking**: already wired transitively —
  `merge_results` calls `extraction_cli.commands._merge()`, which calls
  `main.update_manifest_after_extract()` internally. Verified (not
  newly built) with `tests/test_orchestration_manifest.py`, which aligns
  `main.PROJECTS_DIR` with the test hub the way a real deployment's
  single `ENGINEERING_HUB` env var does for both the Flask process and
  the agentic pipeline's `hub` state field.

`tests/conftest.py` adds an autouse per-test SQLite isolation fixture
(`adapters.db.reset_for_path` to a temp file) — needed once E4 made
`CacheStore` actually hit the DB; before the fix, cache tests were
silently no-ops against the real dev `studio.db`.

## The Grid (tile matrix) system

A row/column layout derived from the graph, not stored as an
independent source of truth — `grid_positions` (SQLite) is fully
rebuildable from `nodes`/`edges` at any time via
`extraction/agents/grid_layout.compute_grid()`.

- **Rows** = one per process stream, walked via `stream`-kind edges.
  Fan-outs (splits) stay in the main row along the first-followed
  branch; every OTHER branch head starts its own row (not a singleton
  row per node — the earlier first-successor-only walk under-handled
  branched/cyclic topology; pure recycle loops with no source node are
  also walked as one connected chain).
- **Columns** = topological (flow) order within a row.
- **Alignment** (v1: `equipment_ref` + shared `area`) propagates a
  column shift across rows ONLY along real graph relationships — an
  instrument aligns under its parent equipment; unrelated rows never
  shift on an unrelated insert. This is what makes "insert a valve
  between A and B" reflow correctly instead of moving things that have
  no reason to move.
- **Persistence**: `save_grid()`/`load_grid()`, one row per node, PK
  `(pid, node_id)`. Recomputed once per Describe TURN (not per tool
  call) in `describe_workflow._dispatch()`, after any turn that produced
  write ops — covers `update_node` (area/move changes shift alignment
  groups) without per-tool opt-in flags.
- **Rendering**: `plantsketch-desktop`'s Canvas has a 4th layout mode
  ("Grid") — `get_grid_positions` (Rust) → `gridLayout.ts` (row/col →
  pixel), falling back to Dagre when no grid has been computed yet.

## The Holistic Agent (disambiguation gate)

Runs before Authoring, Update, AND Deletion (not a specialist graph
itself — a plain function call in `describe_workflow.py`, since its job
is deciding whether to dispatch at all). Resolves "add a valve between
V-101 and E-101" as a **grid-adjacency query**, not a tag-pair lookup:
two tags only count as the match if their specific occurrences are
actual neighbors (`grid_service.find_adjacent_cell_pairs` — same row +
adjacent column, or a real edge). This is what correctly disambiguates
both a duplicated tag (two V-101s) and a tag with multiple distinct
neighbors elsewhere in the drawing — both surface identically as "more
than one adjacent pair matched."

- **Tag extraction**: LLM first (`describe_holistic.md`, instructed to
  list only *existing* references, never the thing being created),
  regex fallback on any failure (`[A-Z]{1,5}-\d{1,5}[A-Z]?`, filtered to
  tags that exist in the project via exact match — `search_graph`'s
  `LIKE` matching is deliberately NOT used for existence checks, since
  it would false-positive "V-1" against an existing "V-101").
- **Intent-aware resolution**: `update`/`deletion` and single-tag cases
  use the single-tag duplicate-count path; pair-adjacency runs only for
  `authoring`/`solution` with 2+ tags, or when the message literally says
  "between". A brownfield request such as "add a pressure package on
  PI-1110 in the feed subsystem, like PT-1111" names tags that are not
  neighbours, and pair-adjacency would wrongly block it. A rename ("FT-101 to FT-102") surfaces two
  tag-shaped strings but must resolve on `tags[0]` only — the new name
  isn't an existing reference to disambiguate.
- **Clarification is a real conversation**, not a re-send-the-whole-
  sentence loop: pending context (original message, intent, extracted
  tags, candidates, round) persists in the `describe_pending` table,
  surviving restarts like the deletion interrupt does. The engineer's
  next message is interpreted as: a numeric selection (`"2"`, `"option
  2"`), a detail match against a candidate's area/row, an unrelated new
  request (dropped — never inherits the old half-spent round budget),
  or additional detail merged into the original request and re-resolved.
  Bounded at `MAX_CLARIFICATION_ROUNDS = 2`, after which the first
  candidate is used and the reply says so explicitly.
- **Fail-open in two layers**: a caught provider error inside tag
  extraction silently falls back to regex; an uncaught failure one
  layer up is caught by `@retryable_node` and resolves to `no_target`
  (proceed unresolved) rather than blocking authoring/update/deletion —
  a UX safeguard, not a safety-critical gate like Deletion's own
  confirm-interrupt.
- **`insert_between`** (repository.py): the atomic tool for "add X
  between A and B" — adds the node, connects A→X→B, and removes the
  stale direct A→B edge in one transaction. Takes `node_a`/`node_b` as
  unique node ids (from the Holistic gate's `resolved_target`), not
  tag strings — using tags there would reintroduce the exact ambiguity
  the gate just resolved.

## Brownfield retrofit: digitise → retrofit → export

Plan and status: `docs/BROWNFIELD_IMPLEMENTATION_PLAN.md`.

- **Routing.** `router.state_aware_intent` sends authoring/solution wording
  that mentions systems, subsystems, packages, accessories or tie-ins to
  `brownfield` when the project already holds a digitised graph. The
  workflow refuses a brownfield turn on an empty project with a message
  to digitise first (checked before the Holistic gate).
- **Which subsystem?** After the Holistic gate, `describe/services/subsystem_gate.py`
  asks the engineer which subsystem a retrofit goes into. It asks when the
  named subsystem matches several groups, or when the request adds equipment,
  the project has subsystems, and no tag in the message already belongs to
  one. No model call is involved. The question persists in `describe_pending`
  with `kind: "subsystem"`. A reply can be a number, a subsystem or system
  name, or "none". The chosen group reaches the agent as a
  `[Plant group confirmed: ...]` note, and the prompt tells it to use exactly
  that group.
- **Tools.** Prompts no longer hand-write signatures: `base.tool_catalog`
  renders each registry from `inspect.signature` into `{tool_catalog}`, so
  a documented argument can never drift from the code. Brownfield has 25
  tools and `max_steps=20` (greenfield/solution 20, others 8–12).
- **What the model decides vs what code builds.** The model picks the
  package, anchor tag and subsystem. `add_instrument_package` builds every
  accessory (root valve, siphon/manifold, transmitter, controller, positioner,
  actuator, control valve), the four-way edges, placement and hierarchy
  assignment deterministically from `services/instrument_packages.py`, and
  numbers tags with `next_tag` without reusing one.
- **Writes are idempotent and non-destructive.** `add_edges` skips an edge
  that already exists (a repeat is a NOOP, not a write); `insert_between`
  and `break_line` keep the original run's line kind. Every authored row
  carries `extra_json.origin = "authored"`, and both extraction pipelines
  carry authored rows through re-extraction whatever `source_id` is. The
  database mirrors that marker into `nodes.origin` / `edges.origin` with
  insert triggers (`adapters/db.py` `ORIGIN_SQL`, identical in `schema.rs`),
  so rows from every writer, Python or Rust, are classified the same way.
- **Placement.** `services/placement.py` puts new nodes in free 0–1 space
  near the anchor, honouring direction words ("above", "left of"), and
  inherits the anchor's drawing, page and page size.
- **Specifications are never invented.** `services/asset_specs.resolve`
  uses the MongoDB asset inventory when `STUDIO_ASSET_INVENTORY=mongodb`,
  then specs the engineer stated; otherwise the node is stored with
  `spec_status: "unspecified"`.
- **Hierarchy.** `services/hierarchy.py` (site › plant › unit › area ›
  system › subsystem) backs `list_hierarchy`, `get_subsystem`,
  `create_system`, `create_subsystem`, `assign_to_subsystem`,
  `get_subsystem_contents` and `sync_hierarchy`.
- **After writes.** The workflow validates loops touched by the turn (the
  reply mentions only incomplete ones) and, unless `STUDIO_AUTO_EXPORT=off`,
  regenerates the connectivity JSON and YMPL under `projects/<pid>/exports/`
  (`services/export_refresh.py`).
- **Geometry.** Both pipelines persist page sizes, line polylines and
  junctions (`services/geometry_store.py`, tables `geometry_pages`,
  `geometry_lines`, `geometry_junctions`); edges keep `line_indices`. A
  separate vision pass per page (`services/llm_flow_annotation_service.py`,
  switched off with `STUDIO_FLOW_ANNOTATIONS=off`) adds flow arrows and
  electric heat tracing as `flow_arrow` / `heat_trace` rows in
  `geometry_lines`. The line tracer records neither, and its stitching step
  would lose per-run annotations anyway.
- **Exports.** `adapters/connectivity_export.py` writes schema 2.0.0 (the
  fixture format, validated by `schemas/connectivity_graph_2_0_0.schema.json`)
  or 2.1.0 (adds id, origin, spec_status and hierarchy). Projects digitised
  before geometry persistence export topology with
  `metadata.geometry: "unavailable"`. Flow direction resolves as
  `arrow-preassign` → `BFS(root)` → `propagation(node)` →
  `geometric-fallback`. `electric_heat_trace`, `loop_groups` and
  `spatial_clusters` are filled from stored geometry and loops.
  `adapters/ympl_export.py` is the only
  YMPL writer; the desktop spawns `export_ympl_cli.py` rather than building
  YAML in Rust.
- **Orchestration.** `run_app_request({"mode": "brownfield", "source_path",
  "message"})` digitises only when the project has no graph, then runs the
  brownfield turn.

## Ollama: the local model

Ollama runs on this machine (`http://localhost:11434`). The installed model is
`qwen2.5vl:3b` (Qwen 2.5-VL, 3.8B parameters, 4-bit; reads images), stored in
`D:\ollama_models` (the `OLLAMA_MODELS` user variable). Every other provider's
config is settings-table/UI-only by design (see `adapters/config.py`'s docstring).
Ollama alone also reads `.env`:

| Variable | Value | |
|---|---|---|
| `OLLAMA_BASE_URL` | `http://localhost:11434` | the local server |
| `OLLAMA_MODEL` | `qwen2.5vl:3b` | the model for both tiers (Ollama models are one size class) |
| `OLLAMA_TIMEOUT_S` | 900 (default) | one call; a 1500 px drawing tile took 8-9 min on this CPU |

The app uses it only when `LLM_PROVIDER=ollama` (or `get_provider('ollama')`); the
default provider stays DeepInfra. Measured on two pid15 reading tiles (2026-10-17), the
3B model read 1 of 52 and 0 of 41 printed tags, so it is not fit for digitising.

## Wiring status

This layer is no longer a side-car. Both workflows are reachable from the
desktop application:

- **Extraction.** `src-tauri`'s `run_extraction` command resolves its script
  through `database::paths::extraction_engine()`. Set
  `STUDIO_EXTRACTION_ENGINE=agentic`, or the `extraction_engine` settings key,
  to run `run_agentic.py` instead of `extract_cli.py`. Default stays
  `classic`, so an existing install does not change behaviour until someone
  opts in. Both scripts take the same positional arguments plus `--source-id`
  and `--llm-only`, and emit the same NDJSON contract, so the Rust side drives
  either one unchanged. The chosen engine is emitted as an
  `{"stage":"engine"}` progress event.
- **Describe.** The Describe screen has an **Agent mode** toggle. With it on, a
  turn goes to `describe_agent_turn` (Rust) which spawns
  `run_describe.py --json`; with it off the previous client-side LLM turn runs
  exactly as before. The toggle is per-browser and off by default.

  Spawning, rather than calling the Flask `/api/agent/describe` blueprint, is
  deliberate and matches `fetch_svg_export`: `security.py` installs a
  fail-closed guard requiring a Bearer token on every `/api/*` request, and the
  desktop app holds no Studio session, so that route answers 401. The blueprint
  remains available for browser and automation callers that do hold a token.

`run_describe.py --json` prints exactly one line prefixed with
`@@DESCRIBE_RESULT@@`. The agents stream NDJSON progress on the same stdout, so
a caller cannot simply parse the whole stream; it scans for that prefix. The
Rust constant and the Python constant are pinned together by
`tests/test_credentials_and_resolve.py::test_rust_parses_the_same_sentinel`.

## Detection: pure LLM, no ML fallback

Detection is resolved in ONE place, `services/detection_router.py`, and it only
ever returns the vision-LLM detectors. No trained model participates: no
YOLOv8, no U-Net, no RapidOCR, and no fallback to any of them.

An earlier version of that router offered `llm`, `cv` and `auto` engines, with
`auto` falling back to the trained detectors when the provider could not see
images. That reintroduced exactly the ML involvement this design forbids, so
the CV engine and the fallback were removed. `STUDIO_DETECTION_ENGINE` is still
read, but `llm` is the only accepted value; a stale `cv` or `auto` is logged
and ignored.

Two further places could still reach a trained model, and no longer can:

- `orchestration.warmup()` called `bootstrap.cv_bootstrap._init_cv_models()`,
  which loaded YOLOv8, RapidOCR and U-Net on **every agentic extraction run**.
  It now checks once that the configured model can accept an image and raises
  `FatalAgentError` if not, because with no fallback there is no way to
  continue and a silent empty run would look like a blank drawing.
- The trained entry points themselves now raise `MLDetectionDisabled`
  (`services/_ml_disabled.py`).

The three legacy modules are retained for their classical geometry -- tiling,
non-max suppression, box merging, line grouping and direction classification,
leader-line filtering, parallel-line splitting, snapping. That code is
arithmetic over coordinates with no learned weights, it is genuinely reused by
the vision-LLM detectors, and deleting the modules would mean duplicating it.

`torch`, `torchvision`, `ultralytics` and `rapidocr-onnxruntime` are no longer
dependencies and the Dockerfile no longer installs PyTorch, so **no model
weights are needed**. `tests/test_detection_router.py` imports the entire
detection and extraction stack and then asserts none of those packages is in
`sys.modules`, which is the strongest guarantee available that this pipeline is
ML-free.

`GET /api/agent/health` reports `detection_engine`, `provider_vision` and
`no_ml_loaded`.

## Document identity

`run_agentic.py` takes `--source-id`, threaded through `ExtractionState` into
`merge_results`. Page results are scoped with the CLASSIC helpers
(`_id_prefix` / `_scope_ids` / `_fallback_drawing`), not the old 0-based
`p0_` prefix, and every node is stamped with `source_id`, `page`, `page_w`,
`page_h` and `drawing`. Without this, two documents extracted into one project
both produced `p0_n1`, and the nodes table is keyed `(id, pid)`, so the second
extraction silently replaced the first document's rows. Pinned by
`tests/test_agentic_source_identity.py`.

## Entry points

```bash
python run_agentic.py  <hub> <pid> <drawing.pdf> [--source-id N] [--llm-only]
python run_describe.py <hub> <pid> "add a pump P-101"     # describe
python run_describe.py <hub> <pid> --resolve confirm      # pending delete
python run_describe.py <hub> <pid> "..." --json           # machine-readable
python test_ollama.py --url http://<host>:11434 --model <name>  # Ollama test
python export_connectivity_cli.py <hub> <pid> [--schema 2.1.0]
python export_ympl_cli.py <hub> <pid> [--topology-only]
python benchmarks/run_benchmark.py --dry-run               # no model calls
python benchmarks/run_benchmark.py --limit 1 --confirm-cost  # live, costs money
```

Programmatic / API:
- `agents.orchestrator.workflows.app_workflow.run_app_request(payload)`
- Flask blueprint `agents.describe.api.describe_agent_bp`
  (`POST /api/agent/describe/<pid>`, `/resolve`, `GET /api/agent/health`)
  — register with `app.register_blueprint(describe_agent_bp)`.

## Deliberate divergences from the reference

- One central prompt loader + one JSON armor (the reference duplicates
  these per domain).
- No `ports/` layer (vestigial/empty in the reference checkout).
- Lazy per-call LLM factory instead of module-level singletons (keeps
  imports key-free for tests and tools).

## Testing

`tests/test_agents_scaffold.py` (extraction + infra),
`tests/test_extraction_multipage.py` (E1 — namespacing, page collection,
real multi-page PDF rendering, 2-page fan-out end-to-end),
`tests/test_harness_agent.py` (E5 conventions injection + E4 usage
recording), `tests/test_orchestration_cache.py` (E4 cache get/put,
per-project scoping, usage totals), `tests/test_orchestration_manifest.py`
(E6 manifest updates), `tests/test_describe_agent.py`
(describe specialists), `tests/test_holistic_agent.py` (disambiguation
gate + `insert_between` + deletion targeting), `tests/test_grid_layout.py`
(tile grid algorithm + branching/cycles + Describe wiring), and
`tests/test_ollama_cli.py` / `test_ollama_host_selection.py` (Ollama)
all run without CV dependencies or API keys: tool boundaries are
monkeypatched, controllers run in rules-only mode, and
`use_llm_router=False` keeps router tests deterministic and offline.
`tests/conftest.py` isolates every test's SQLite DB from the real
`studio.db` automatically (autouse fixture) — no per-test setup needed.

A module that manages its own hub and seeds the settings table once (the
end-to-end extraction tests) must declare `pytestmark = pytest.mark.own_db` to
opt OUT of that fixture. Module-scoped fixtures run before function-scoped
autouse ones, so without the marker the isolation fixture re-points
`adapters.db` immediately after the hub fixture and discards the seeded
provider key — which made every end-to-end test die on "Anthropic API key not
set" despite seeding a dummy one.

New suites added alongside the wiring work:
`tests/test_detection_router.py` (engine selection, the vision guard on every
provider, the missing-weights diagnostic),
`tests/test_agentic_source_identity.py` (document/page identity parity with the
classic engine), and `tests/test_credentials_and_resolve.py` (a tree-wide
secret scan, plus the "nothing pending" resolve path).
