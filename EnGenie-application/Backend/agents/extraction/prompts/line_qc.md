ROLE
QC for vision-LLM pipe/signal line tracing on one P&ID page. There is no
U-Net or Hough transform behind this detector — every run was traced
tile-by-tile by a vision LLM against a driving prompt (line_trace.md), then
audited once against the full page (line_verify.md) before reaching you.

CONTEXT VARIABLES

**Total detected line length (px):**
{total_line_length_px}

**Page ink density (dark pixel fraction):**
{page_ink_density}

**Segments detected:**
{segments}

**Open endpoints (touching no symbol):**
{open_endpoints}

**Segments per symbol (healthy range 1.5 - 6.0):**
{segments_per_symbol}

**Suspected fused parallel lines:**
{suspected_fused_parallels}

**Leader-line candidates (short one-ended segments near symbols):**
{leader_line_candidates}

**Stricter re-scan prompt already used this run:**
{reprompt_used}

**Retries already used (max 2):**
{retries_used}

AVAILABLE ACTIONS
Multiple non-retry actions may be combined; a retry may not be combined
with anything else.
- proceed
- retry_reprompt          Re-run every tile with a stricter re-scan
                          instruction appended to the tracing prompt
                          (follow faint/occluded lines further, re-check
                          EXCLUSIONS for over-application). Use ONLY when
                          segments_per_symbol < 1.0 and ink density says
                          lines must exist — but not if reprompt_used is
                          already true this run (it's a one-shot
                          escalation, not a toggle). Costs real inference
                          time (every tile is re-traced).
- unfuse_parallels        Run the parallel-line splitter. Use when
                          suspected_fused_parallels > 3.
- drop_leaders            Run the leader-line filter. Use when
                          leader_line_candidates > 10.
- classify_styles         Run the CV dashed/solid classifier as a
                          cross-check on the LLM's own style tagging.
                          Cheap; default ON.

OUTPUT SCHEMA
{"verdict": "ok" | "suspect", "actions": ["..."], "reason": "<one sentence>"}
