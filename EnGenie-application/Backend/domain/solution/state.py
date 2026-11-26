from typing import Any, TypedDict

class SolutionState(TypedDict, total=False):
    """Domain state specifically for the Solution Architecture workflow."""
    
    # Core Data
    instruments: list[dict[str, Any]]
    accessories: list[dict[str, Any]]
    skip_standards: bool
    selected_vendors: list[str]
    strategy_vendors: list[str]
    fallback_vendors: list[str]
    vendor_priority: dict[str, int]
    applied_standards: list[dict[str, Any]]
    
    # Clarification
    clarification_needed: bool
    clarification_questions: list[str]
    clarification_context: dict[str, Any]

    # Holistic agent (merged system-scope holism gate + requirements extraction)
    awaiting_holistic_confirmation: bool

    # Designed solution (standalone parallel solution-build agent output).
    # Written ONLY by solution_build_node so it never collides with the BOM
    # pipeline's channels in the parallel superstep.
    designed_solution: dict[str, Any] | None
    pid_graph: dict[str, Any] | None
    active_pid_graph: dict[str, Any] | None
    pid_project_type: str | None
    awaiting_pid_clarification: bool
    pid_clarification_question: str | None
    pid_clarification_options: list[str] | None
    existing_pid_image_url: str | None

    # Modification flow flags. Must be declared: LangGraph drops undeclared
    # keys at node boundaries (see domain/search/state.py for the full story).
    has_new_items_from_modification: bool
    skip_spec_doc_values: bool
