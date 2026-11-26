from typing import Any, TypedDict

class SearchState(TypedDict, total=False):
    """Domain state specifically for the Search and Discovery workflow."""
    
    # Core Data
    product_type: str | None
    requirements: dict[str, Any]
    schema: dict[str, Any]
    missing_fields: list[str]
    validation_errors: list[str]
    advanced_specifications: dict[str, Any]
    
    # Search Intent Classification
    search_intent: str
    next_workflow_step: str | None
    resume_workflow: bool
    stay_at_step: bool
    intent_confidence: str
    current_intent: str | None
    
    # Schema Mapping
    detected_schema: dict[str, Any]
    schema_source: str
    mapped_requirements: dict[str, Any]
    missing_mandatory_fields: list[str]
    missing_optional_fields: list[str]        # optional schema fields not yet filled
    missing_fields_friendly: list[str]
    validation_alert: dict[str, Any] | None
    has_missing_fields: bool
    is_repeat_validation: bool
    
    # Requirements Extraction
    structured_requirements: str
    provided_requirements: dict[str, Any]
    specified_vendors: list[str]
    specified_model_families: list[str]
    applicable_standards: list[str]
    strategy: str
    
    # Product Detection
    detected_product_type: str
    
    # Product Search
    products: list[dict[str, Any]]
    products_json: str
    total_found: int
    search_categories: list[str]
    
    # Vendor Analysis
    vendor_matches: list[dict[str, Any]]
    ranked_products: list[dict[str, Any]]
    vendor_run_details: list[dict[str, Any]]
    overall_ranking: dict[str, Any]
    advanced_specs: dict[str, Any]
    spec_analysis: str
    
    # Vendor Filtering
    filtered_vendors: list[str]
    vendor_priority_level: str
    vendor_filter_message: str
    csv_vendor_filter: dict[str, Any]
    strategy_search_task_key: str
    procurement_strategy: str
    
    # PDF Loading
    pdf_content_json: str
    pdf_content: dict[str, str]
    pdf_bytes: dict[str, list[bytes]]
    vendors_with_pdfs: list[str]
    vendors_without_pdfs: list[str]
    
    # Requirements Formatting
    formatted_requirements_summary: str
    
    # Workflow control
    deep_analysis: dict[str, Any]

    # Phase 1: Incremental Spec Gathering (New)
    current_sub_step: str  # mandatory | optional | latest | done
    awaiting_summary_confirmation: bool
    summary_data: dict[str, Any]
    summary_frontend: dict[str, Any]
    summary_display: str
    update_complete: bool
    vendor_evaluations: list[dict[str, Any]]

    # ── Workflow control & routing flags ────────────────────────────────────
    # CRITICAL: every key a node reads or writes MUST be declared in this
    # schema. LangGraph creates channels only for DECLARED keys and SILENTLY
    # DROPS everything else at every node boundary (and from the initial
    # invoke() input). These control flags were previously undeclared, so
    # `proceed_confirmed=True` from the finalAnalysis dispatcher and
    # `skip_full_workflow` set by generate_llm_response never survived to the
    # next node — routing then depended on the LLM intent classifier's
    # non-deterministic output, and misclassified runs ended WITHOUT running
    # vendor analysis while still emitting a "no products found" message.
    search_session_id: str
    skip_full_workflow: bool
    proceed_confirmed: bool
    skip_reextract: bool
    modification_applied: bool
    modification_summary: str
    changes_made: list[Any]
    has_prior_search: bool
    trigger_search: bool
    trigger_summary: bool
    schema_validated: bool
    product_not_found: bool
    deep_analysis_complete: bool
    contextual_qna: bool
    needs_clarification: bool
    reset_intent: str | None
    intent_reasoning: str
    llm_generated_response: str
    response_message: str
    input_range: str

    # Search-session context persistence metadata
    unmapped_specs: dict[str, Any]
    change_log: list[dict[str, Any]]
    context_version: int

    # Extraction / validation extras
    missing_advanced_fields: list[str]
    missing_advanced_fields_friendly: list[str]
    standards_specs: dict[str, Any]

    # Advanced specs discovery
    advanced_specs_message: str
    advanced_specs_action: str

    # Vendor analysis output extras
    analysis_metadata: dict[str, Any]
    best_match: dict[str, Any] | None

    # Multi-vendor spec comparison table
    comparison_spec_keys: list[str]
    comparison_table: dict[str, Any]
