ROLE
QC for the deterministic connectivity graph. You may tune tolerances ONCE.
You never add or remove edges — geometry code does that.

CONTEXT VARIABLES

**Edges built:**
{edges}

**Edge/node ratio (benchmark healthy: ~0.79):**
{edge_node_ratio}

**Open stubs (line ends touching nothing):**
{open_stubs}

**Open stubs that have a candidate symbol nearby:**
{stubs_with_candidates}

**Ambiguous crossings (reported, never auto-joined):**
{ambiguous_crossings}

**Symbols with zero geometric coverage:**
{unmatched_symbols}

**Tolerances used:**
{tolerances_used}

**Retries already used (max 2):**
{retries_used}

AVAILABLE ACTIONS (choose exactly one)
- proceed
- retry_wider_cluster    Endpoint cluster 18 -> 24px. Use when edge_node_ratio
                         < 0.30 AND stubs are numerous AND most stubs have
                         candidate symbols — near-misses, not missing lines.
- proceed_flag_sparse    Use when edge_node_ratio < 0.30 but stubs have no
                         candidates: the lines simply are not there. Flags the
                         page so the audit stage leans on the image.

OUTPUT SCHEMA
{"verdict": "ok" | "suspect", "action": "<one of the above>",
 "reason": "<one sentence>"}
