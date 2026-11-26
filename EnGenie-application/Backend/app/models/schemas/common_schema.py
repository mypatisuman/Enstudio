"""
Common schemas — shared Pydantic models used across multiple domains.
"""
from pydantic import BaseModel, ConfigDict, Field
from typing import Any


class ErrorResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool = False
    error: str
    error_code: str | None = None
    error_id: str | None = None


class SuccessResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool = True
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)
