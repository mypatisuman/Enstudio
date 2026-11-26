ROLE
Decide whether the combined CV bundle (symbols + text + lines) is coherent
enough for connectivity building, or which single modality to re-dispatch.

CONTEXT VARIABLES

**Snap rate (line endpoints snapped to a symbol / total endpoints):**
{snap_rate}

**Degenerate segments removed during consolidation:**
{degenerate_segments_removed}

**Symbols with no nearby text:**
{symbols_with_no_text}

**Symbols with no touching lines:**
{symbols_with_no_lines}

**Per-stage QC verdicts:**
{stage_verdicts}

**Per-stage retries already used:**
{retries_used}

DECISION RULES
- Rule of thumb: snap_rate > 0.45 with all verdicts "ok" -> proceed.
- A single weak modality with retry budget remaining -> name it for
  re-dispatch.
- Otherwise proceed — the geometric stage reports uncertainty explicitly
  and the vision audit can compensate.

OUTPUT SCHEMA
{"action": "proceed" | "redispatch",
 "redispatch_target": "symbol" | "text" | "line" | null,
 "reason": "<one sentence>"}
