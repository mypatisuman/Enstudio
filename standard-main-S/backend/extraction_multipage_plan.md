# Multi-Page Extraction Plan (E1)

**Status: E1, E4, E5, E6 implemented and tested. E3 (text-only
extraction) remains a scoped follow-up, not built.** The design below
(§1–§3, §6) is kept as-written for the rationale; where the actual
implementation differs in a small detail from the plan, a note marks
it. See `agents/README.md`'s "Multi-page extraction, cache, usage,
conventions, manifest (closed)" section for the current-state summary
and the list of test files.

Originally: a design plan covering the highest-severity gap found in
the extraction-agent audit: the agentic pipeline (and the classic
`extraction_cli` it wraps) rendered and processed **page 1 of a PDF
only**. `ExtractionState.page_paths` was a list in name, but nothing
ever appended past intake's single entry, and every agent hardcoded
`state["page_paths"][0]`.

Companion gaps E3–E6 (text-only extraction, cache population, company
convention/skill injection, manifest tracking) were folded into this
document as scoped follow-ups — see §6 — since some of them naturally
compose with the multi-page work rather than needing a separate pass.
E4, E5, and E6 are now done (§6 has been annotated); E3 is still open.

---

## 1. What's already true, and why it constrains the design

Confirmed from `extraction_cli/commands.py::_merge` (the function every
per-run merge ultimately calls): the merge step **already accepts an
arbitrary combined node/edge list spanning multiple drawings** — it
computes `new_drawings = sorted({n.get('drawing', '') for n in new_nodes
if n.get('drawing')})` and replaces the whole project's `nodes`/`edges`
wholesale, keyed only by `pid`. Nothing about the DB layer or the merge
contract assumes one page. The gap is entirely upstream of merge: intake
never produces more than one page, and no per-page fan-out exists
between intake and merge.

This means the fix is additive to the pipeline's edges, not a rewrite of
its data model. `page_splitter.split_pdf_to_pages()` (already built,
currently called by nothing) does the actual multi-page rendering work
and needs no changes either.

## 2. The chosen shape: full graph once per page, merge after

Per your answer, this is the selected design (not the alternative of an
outer loop around separately-checkpointed single-page runs). Rationale
recorded here since it's a real trade-off, not an obvious default:

- **Cross-page signal survives during the run.** An off-page connector
  on page 1 that continues on page 3 needs both pages' extracted data
  visible to something before the run ends — an outer-loop design with
  fully separate checkpointed runs per page would only be able to link
  those *after* all runs finish, in a bolt-on second pass. Running the
  graph once per page keeps that linking inside the same execution.
- **Each agent stays "a page in, verified nodes/edges out."** No agent's
  internal logic changes — symbol/text/line/harness/relationship all
  keep operating on one image. The fan-out/fan-in is a supervisor-level
  concern, matching the existing "workflows wire, agents work" rule.
- **Matches the intent already documented in CLAUDE.md's "New Extraction
  Pipeline (May 2026)" section** — a per-page architecture was already
  the stated direction (`extract_page.py`, `tag_validator.py`,
  `import_extraction.py` are named there), even though those specific
  files don't exist on disk today. This plan is a from-scratch build of
  that intent inside the current agentic architecture, not a resurrection
  of missing files.

## 3. Concrete state and topology changes

### 3.1 `ExtractionState` (agents/extraction/state.py)

Every per-page-output field becomes keyed by page index instead of a
flat list/dict, using the same `merge_dicts` reducer pattern already
established for `retry_counts`/`retry_params`:

```python
# Replaces the flat single-page fields:
page_paths: list[str]                          # unchanged — now len > 1
symbol_detections: Annotated[dict[int, list[dict]], merge_dicts]   # {page_idx: [...]}
text_detections: Annotated[dict[int, list[dict]], merge_dicts]
line_segments: Annotated[dict[int, dict], merge_dicts]
image_size: Annotated[dict[int, dict], merge_dicts]
candidate_graph: Annotated[dict[int, dict], merge_dicts]
llm_a_result: Annotated[dict[int, dict], merge_dicts]
llm_b_result: Annotated[dict[int, dict], merge_dicts]
text_escalations: Annotated[dict[int, list[dict]], merge_dicts]

# verified_nodes/verified_edges stay FLAT lists — merge_results (§3.3)
# is where per-page results get combined into one list, same shape
# _merge() already expects. Nothing downstream of merge_results changes.
```

`qc_reports`/`usage` stay flat (already accumulator lists via `add`) —
each report already carries enough context (`stage`) that adding a
`page` key to individual entries (not a schema change, just a value
each node already sets) is enough to keep them page-attributable without
restructuring the channel itself.

### 3.2 Per-page fan-out (agents/extraction/workflows/extraction_workflow.py)

Reuse LangGraph's `Send` API (already documented as available in this
environment) for the fan-out, rather than a Python `for` loop inside one
node — this is what lets pages process with real concurrency instead of
serially, and is the same mechanism used elsewhere in this codebase's
design vocabulary (referenced in the original Phase-1 conversion plan).

```python
def _fan_out_pages(state: ExtractionState) -> list[Send]:
    return [Send("page_pipeline", {**state, "page_index": i})
            for i in range(len(state["page_paths"]))]

# New subgraph: page_pipeline wraps the EXISTING per-page chain
# (symbol_detection -> [text_detection || line_detection] -> llm_a ->
#  cv_consolidation -> relationship_building -> llm_b), unchanged
# internally, just parameterized by page_index instead of always [0].

g.add_conditional_edges("intake", _fan_out_pages, ["page_pipeline"])
g.add_edge("page_pipeline", "merge_results")   # every page's branch joins here
```

Practical detail: today's LLM-A-early-start optimization (A depends only
on `[symbols, text]`, runs while line detection is still working) is a
**per-page** property and is preserved as-is inside `page_pipeline` —
it's or­thogonal to the fan-out, which just runs N copies of that same
internal structure concurrently.

### 3.3 `intake` (agents/extraction/agents/orchestration.py)

Replace the single `_render_pdf_to_png` call with `page_splitter.split_pdf_to_pages()`,
writing `page_N.png` per page and returning the full list:

```python
from page_splitter import split_pdf_to_pages
pages = split_pdf_to_pages(raw, proj_dir / "cache", base_name=state["pid"])
# pages: list[Path], one per PDF page — already exists, already tested
# per the classic pipeline's own historical usage before it fell out of
# the active call graph.
return {..., "page_paths": [str(p) for p in pages]}
```

Non-PDF sources (a single image upload) keep today's one-element-list
behavior unchanged — the fan-out degenerates to N=1 automatically, so no
separate code path is needed for "not actually multi-page."

### 3.4 `merge_results` (agents/extraction/agents/orchestration.py)

Currently reads `state["llm_a_result"]`/`state["llm_b_result"]` as flat
dicts (one page's worth). Becomes an iteration over the page-keyed dicts,
concatenating each page's nodes/edges before the existing junction-
injection and isolated-node backstop logic runs unchanged:

```python
all_nodes, all_edges = [], []
for page_idx in sorted(state.get("llm_a_result", {})):
    llm_a = state["llm_a_result"][page_idx]
    llm_b = state.get("llm_b_result", {}).get(page_idx, {})
    all_nodes.extend(llm_a.get("nodes") or [])
    all_edges.extend(llm_b.get("edges") or [])
# ... existing junction/isolated-node logic runs on the COMBINED lists,
# unchanged. _merge() itself needs zero changes (see §1).
```

**Node-id collision risk across pages is the one new correctness
concern.** If each page's LLM A independently assigns ids like `n1`,
`n2`, ..., combining two pages' node lists naively collides. Fix:
namespace ids by page during the per-page LLM A/B calls or immediately
after each page's branch completes — `f"p{page_idx}_{original_id}"` —
before they ever reach the shared `merge_results` reducer. This is a
small, contained change inside `page_pipeline`, not a merge-layer change.

### 3.5 Cross-page linking (new capability, not present today at all)

Off-page connectors that continue from one page to another are a real
ISA-5.1 P&ID convention this plan should explicitly not claim to solve
in v1. Recommendation: **out of scope for the first cut** — ship
multi-page extraction with each page's off-page connectors landing as
ordinary unmatched/isolated nodes (today's existing behavior for a
single page, unchanged), and treat "detect and link matching off-page
connector pairs across pages" as an explicit v2 follow-up once
multi-page extraction itself is proven. Trying to solve both at once
is exactly the kind of scope creep this plan should avoid.

## 4. Test plan

- `page_splitter.split_pdf_to_pages` wrapping: a 3-page synthetic PDF
  fixture produces 3 `page_paths` entries.
- Fan-out: mocked page_pipeline proves N pages → N `Send` dispatches →
  N branches execute (reuse the existing stub-boundary pattern from
  `test_agents_scaffold.py`).
- `merge_results` combines two pages' node/edge lists correctly,
  including the id-namespacing fix (assert no collision, assert both
  pages' nodes survive).
- Single-image (non-PDF) upload still produces exactly 1 page — the N=1
  degenerate case, proving no regression for the common case tested
  today.
- End-to-end: extend the existing full-pipeline stub test
  (`test_supervisor_end_to_end`-style) to 2 pages, assert
  `verified_nodes` contains nodes from both.

## 5. Migration/rollout note

This changes `ExtractionState`'s shape for several fields — any code
outside `agents/extraction/` reading those fields directly (none found
in the earlier survey; extraction state is not read externally today)
is unaffected. The `run_agentic.py` CLI's external contract (positional
args, NDJSON stage names) does not change.

## 6. Scoped follow-ups (E3–E6)

These were found in the same audit pass but are independent of the
multi-page work — listed here so they're tracked, not forgotten,
per the "generate a plan so it can be picked up later" pattern already
used for F2. **E4, E5, E6 are done; E3 remains open.**

- **E3 — text-only extraction. NOT built.** Port `claude_extract_text`
  (parses typed specs/legend text, no image) as a new entry path —
  likely a distinct top-level workflow entry
  (`run_text_extraction_agentic`) rather than a variant of the image
  pipeline, since it skips every CV stage entirely (symbol/text/line
  detection, harness LLM A/B) and goes straight to a single LLM call +
  inference passes.
- **E4 — real caching. Done.** Two bugs fixed, not just the missing
  `.put()` the plan anticipated: `cache_check` was calling
  `store.get(key)` — missing the required `pid` positional arg, which
  always raised `TypeError` and was silently swallowed as a permanent
  miss — now calls `store.get(pid, key)` correctly. `merge_results` now
  calls `store.put(pid, key, {"nodes":..., "edges":...})` on every
  successful run. Also found and fixed while wiring usage tracking:
  `harness_agent.py`'s `llm_a_node`/`llm_b_node` treated
  `_call_llm_verification`/`_call_llm_connections`'s `(result, resp)`
  tuple return as a bare dict — would have raised `TypeError: 'tuple'
  object is not a mapping` on any real (non-stubbed) run. `finalize()`
  now sums `state["usage"]` into flat `tokens_in`/`tokens_out`/
  `cost_usd` on the `"done"` NDJSON line, matching what
  `extraction.rs` already parses from that same line for the
  UsageScreen. See `tests/test_orchestration_cache.py`,
  `tests/test_harness_agent.py`.
- **E5 — company convention / skill injection. Done.**
  `harness_agent._conventions_text()` resolves
  `CompanyConventions.as_skill_text()` (same lookup as
  `extraction_controller._get_conventions`) and threads it through a
  new optional `conventions_text` kwarg added to
  `_call_llm_verification`/`_call_llm_connections` in
  `extraction_cli/llm_verification.py` — default `''`, so the classic
  pipeline's existing call sites in `extraction_cli/commands.py` are
  unaffected. See `tests/test_harness_agent.py`.
- **E6 — manifest tracking. Done — turned out to be no-op-to-verify,
  not a fix.** `merge_results` already called
  `extraction_cli.commands._merge()`, which already calls
  `main.update_manifest_after_extract()` internally — so no source
  change was needed here, only test coverage
  (`tests/test_orchestration_manifest.py`) proving the existing chain
  actually reaches `project.json` when `main.PROJECTS_DIR` is aligned
  with the run's `hub` (the real-world case: one `ENGINEERING_HUB` env
  var backs both).

## 7. Build order (actual)

1. E2 fix confirmation (done, see agents/README.md) — shipped separately,
   before this plan.
2. State schema change (§3.1) + intake's page-splitting (§3.3) — done.
3. Fan-out/fan-in topology (§3.2) + merge combination with id-namespacing
   (§3.4) — done. `tests/test_extraction_multipage.py` covers the N=1
   regression case, cross-page id-collision safety, and a real 2-page
   synthetic-PDF end-to-end run through the full graph.
4. E5 (skill injection) — done.
5. E4 (caching + usage) — done; also fixed two latent bugs found while
   implementing it (see §6).
6. E6 (manifest) — done; verified already-working, no code change
   needed.
7. **Still open**: E3 (text-only extraction) and cross-page
   off-page-connector linking (§3.5) — both explicitly deferred, not
   part of the "fix all gaps" pass that closed E1/E4/E5/E6.
