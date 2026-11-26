"""Named prompt constants for the Describe workflow, loaded from the
co-located .md files (reference convention: X_PROMPT = load_prompt(...)).
Edit the .md files, not this module.
"""
from agents.prompts import load_prompt as _load

DESCRIBE_ROUTER_V1 = _load("describe_router")
DESCRIBE_HOLISTIC_V1 = _load("describe_holistic")
DESCRIBE_QUERY_V1 = _load("describe_query")
DESCRIBE_AUTHORING_V1 = _load("describe_authoring")
DESCRIBE_UPDATE_V1 = _load("describe_update")
DESCRIBE_DELETION_V1 = _load("describe_deletion")
DESCRIBE_VALIDATION_V1 = _load("describe_validation")
DESCRIBE_SOLUTION_V1 = _load("describe_solution")
DESCRIBE_INPUT_ANALYZE_V1 = _load("describe_input_analyze")
DESCRIBE_GREENFIELD_V1 = _load("describe_greenfield")
DESCRIBE_BROWNFIELD_V1 = _load("describe_brownfield")



