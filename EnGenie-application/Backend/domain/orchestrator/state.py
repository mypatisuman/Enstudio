from datetime import datetime
from typing import Any, Literal, TypedDict

from domain.search.state import SearchState
from domain.solution.state import SolutionState
from domain.chat.state import ChatState

class BaseState(TypedDict, total=False):
    """Generic environmental baseline state properties."""
    user_input: str
    user_id: int | None
    session_id: str
    user_session_id: str | None
    current_page: Literal["solution", "chat", "search"]
    context_memory: list[dict[str, Any]] | None
    
    # Generic Workflows
    active_workflow: Literal["solution", "search", "chat", "admin"] | None
    workflow_step: str | None
    workflow_data: dict[str, Any]
    
    # Cross-module Shared Data
    user_strategy_docs: list[dict[str, Any]]
    user_standards_docs: list[dict[str, Any]]
    user_projects: list[dict[str, Any]]
    
    # Agent generic tracking
    current_agent: str
    agent_status: str
    agent_response: dict[str, Any]
    agent_response_standardized: dict[str, Any]
    error_message: str
    validation_result: dict[str, Any]
    
    # Streams
    stream_id: str | None
    enable_streaming: bool
    
    # Response
    final_response: dict[str, Any]
    error: str | None
    
    timestamp: datetime
    execution_time_ms: float | None
    agent_path: list[str]

    # Hybrid Agentic Memory
    user_interest_description: str | None  # Dynamically generated natural-language description of user interests and specs

class OrchestratorState(TypedDict, total=False):
    """State properties used exactly for high-level intent routing."""
    route_category: str
    target_page: Literal["solution", "chat", "search"]
    requires_routing: bool
    requires_confirmation: bool
    direct_response: str
    confirmation_message: str
    opening_message: str
    decline_message: str
    popup_blocked_message: str
    routing_reasoning: str
    recall_response: dict
    routing_url: str
    routing_message: str

    # Router redirect fields set by classify_search_intent / router classifier.
    # Must be declared or LangGraph silently drops them at node boundaries.
    router_needed: bool
    router_category: str | None
    router_target_page: str | None
    router_requires_routing: bool
    router_url: str
    router_message: str
    router_requires_confirmation: bool
    router_confirmation_message: str
    router_opening_message: str
    router_decline_message: str
    router_popup_blocked_message: str

    warnings: list[str]
    feature_flags: dict[str, bool]
    session_created: bool

class AgenticSystemState(BaseState, OrchestratorState, SearchState, SolutionState, ChatState, total=False):
    """
    Unified global context schema combining all distinct Domain bounds.
    This fulfills the unified TypedDict schema required natively by LangGraph nodes!
    """
    pass
