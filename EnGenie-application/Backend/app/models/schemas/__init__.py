# app/models/schemas — Pydantic request/response schemas
#
# Auth and common schemas are defined here (no domain equivalent).
# Search, chat, and solution schemas live in domain/ as the single source of truth.

from app.models.schemas.auth_schema import LoginRequest, SignupRequest, AuthResponse
from app.models.schemas.common_schema import ErrorResponse, SuccessResponse

from domain.chat.schemas import ChatRequest, ChatResponse
from domain.search.schemas import (
    ProductMatch, VendorAnalysis, RankedProduct, OverallRanking,
    RequirementValidation, SearchRequest, SearchResponse,
)
from domain.solution.schemas import InstrumentSpec, AccessorySpec, SolutionRequest, SolutionResponse

__all__ = [
    # auth
    "LoginRequest", "SignupRequest", "AuthResponse",
    # common
    "ErrorResponse", "SuccessResponse",
    # chat
    "ChatRequest", "ChatResponse",
    # search
    "ProductMatch", "VendorAnalysis", "RankedProduct", "OverallRanking",
    "RequirementValidation", "SearchRequest", "SearchResponse",
    # solution
    "InstrumentSpec", "AccessorySpec", "SolutionRequest", "SolutionResponse",
]
