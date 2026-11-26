"""Named prompt constants, loaded from the dedicated .md files in this
package. Edit the .md files, not this module.

Composition rule: every QC controller prompt = qc_preamble.md + its own
file. The Harness prompts (deletion_justify, unreadable_crops_addendum) and
the tiled/vision detection prompts (symbol_detect, text_read,
text_read_tile, line_trace, line_verify) are used standalone — they
accompany vision calls, not metric decisions.
"""
from agents.prompts import load_prompt as _load


def _qc(name: str) -> str:
    return _load("qc_preamble") + "\n" + _load(name)


AGENT_PREAMBLE = _load("qc_preamble")

SUPERVISOR_ROUTE_V1 = _qc("supervisor_route")
SYMBOL_QC_V1 = _qc("symbol_qc")
TEXT_QC_V1 = _qc("text_qc")
LINE_QC_V1 = _qc("line_qc")
CV_CONSOLIDATION_V1 = _qc("cv_consolidation")
GEOMETRY_QC_V1 = _qc("geometry_qc")

DELETION_JUSTIFY_V1 = _load("deletion_justify")
PROPOSAL_CONFLICT_V1 = _qc("proposal_conflict")
UNREADABLE_CROPS_ADDENDUM_V1 = _load("unreadable_crops_addendum")
SYMBOL_DETECT_V1 = _load("symbol_detect")
SYMBOL_REFINE_V1 = _load("symbol_refine")
FLOW_ANNOTATIONS_V1 = _load("flow_annotations")
TEXT_READ_V1 = _load("text_read")
TEXT_READ_TILE_V1 = _load("text_read_tile")
LINE_TRACE_V1 = _load("line_trace")
LINE_VERIFY_V1 = _load("line_verify")
