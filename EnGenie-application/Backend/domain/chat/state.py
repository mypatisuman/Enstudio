from typing import Any, TypedDict

class ChatState(TypedDict, total=False):
    """Domain state specifically for the conversational and sales workflow."""
    
    # Core RAG Data
    resolved_query: str
    classified_keywords: dict[str, list[str]]
    relevant_collections: list[str]
    search_results: list[dict[str, Any]]
    rag_context: str
    conversation_history: list[dict[str, str]]
    pending_confirmation: dict[str, Any] | None
    
    # Sales Conversational Flow
    sales_step: str | None
    sales_intent: str | None
    data_context: dict[str, Any]
    available_parameters: list[dict[str, Any]]
    added_specs: list[str]
    awaiting_yesno: bool
    knowledge_question_answer: str | None
    requirements_summary: str | None
