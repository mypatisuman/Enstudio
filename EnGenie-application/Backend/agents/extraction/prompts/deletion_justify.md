ROLE
Second-pass connection auditor. You previously audited a proposed P&ID
connectivity graph and deleted an unusually high fraction of the proposed
edges, every one of which was backed by detected line pixels. Justify or
restore each deletion.

CONTEXT VARIABLES

**Edges you deleted:**
{n_deleted}

**Total edges proposed:**
{n_total}

**The deleted edges, with their endpoint and segment context:**
{deleted_edges_with_context}

TASK
Re-examine ONLY these deleted edges against the image. For each edge state:
- "confirm_delete" — you can name the specific visual evidence it is fake
  (e.g. a nameplate leader line, a title-block border line).
- "restore" — you cannot name such evidence.

The default on any doubt is "restore" — a human reviews everything
downstream, and a wrongly deleted pipe is invisible to them while a wrongly
kept one is easy to reject.

OUTPUT SCHEMA
{"decisions": [{"edge": "<from>-><to>", "action": "confirm_delete" | "restore",
 "evidence": "<specific, one sentence>"}]}
