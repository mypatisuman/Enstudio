"""
Chat Workflow Schemas

Pydantic models for the chat workflow's request/response shapes.
"""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field


class ChatRequest(BaseModel):
    user_input: str = Field(description="User's chat message")
    session_id: str = Field(default="default", description="Conversation session identifier")
    user_id: int | None = Field(default=None, description="Authenticated user ID")


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool
    answer: str = Field(default="", description="Assistant's response text")
    source: str = Field(default="", description="Source of the answer (e.g. 'database_with_context', 'conversation_history_only')")
    is_chat_related: bool = Field(default=True, description="Whether the query was chat-related")
    is_followup: bool = Field(default=False, description="Whether this was a follow-up question")
    has_user_context: bool = Field(default=False, description="Whether user-specific context was used")
    keywords_extracted: dict[str, Any] = Field(default_factory=dict, description="Keywords extracted from the query")
    router_result: dict[str, Any] | None = Field(default=None, description="Router result when query is not chat-related")
    error: str | None = Field(default=None, description="Error message if success=False")
