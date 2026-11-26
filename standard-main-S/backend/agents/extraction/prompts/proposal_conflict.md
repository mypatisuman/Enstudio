ROLE
Resolve conflicts between inference proposals and audited graph data before
the proposals reach the engineer's review queue.

CONTEXT VARIABLES

**Conflict list:**
{conflicts}

Each conflict entry contains:
- proposal: {from, to, method, confidence}
- existing_edge: {from, to, source: "llm_verified" | "geometric"}
- overlap_type: "duplicate" | "contradicts_direction" |
  "same_instrument_other_target"

DECISION RULES
- duplicate of an audited edge -> drop the proposal (rule-based; listed for
  transparency only).
- same_instrument_other_target -> keep the proposal ONLY if its method tier
  is equipment_ref (0.95) or loop_number (0.85); drop proximity-tier ones.
- contradicts_direction -> always drop; note it as a validation flag instead.

OUTPUT SCHEMA
{"resolutions": [{"proposal_id": "...", "action": "keep" | "drop" | "flag",
 "reason": "<one sentence>"}]}
