"""
Search Workflow Schemas

Pydantic models for the search workflow's LLM structured outputs
and API request/response shapes.
"""
from typing import Any
from pydantic import BaseModel, ConfigDict, Field

class ProductMatch(BaseModel):
    product_name: str = Field(description="Specific submodel name (e.g., 'STD850', '3051CD') - the exact model being matched")
    model_family: str = Field(default="", description="Model family/series name (e.g., 'STD800', '3051C') - the broader product family this submodel belongs to")
    product_type: str | None = Field(default=None, description="type of the matching product")

    vendor: str = Field(description="Vendor/manufacturer name")
    match_score: int | float = Field(description="Match score from 0-100")
    requirements_match: bool = Field(description="Whether the product meets ALL critical/mandatory requirements (True) or has fundamental gaps (False)")
    reasoning: str = Field(description="Detailed parameter-by-parameter analysis of why this product matches the requirements, including user requirement vs product specification for each parameter")
    limitations: str = Field(description="Detailed analysis of any gaps, limitations, or areas needing verification for each parameter")
    spec_values: dict[str, str] = Field(default_factory=dict, description="Extracted value for each requested comparison spec key, keyed by the same field names as the requirement schema; omitted/empty keys mean the spec wasn't stated in the source")

class VendorAnalysis(BaseModel):
    vendor_matches: list[ProductMatch] = Field(description="Best products match from each vendor")
    vendor_run_details: list[dict[str, Any]] = Field(default_factory=list, description="Execution details for parallel vendor tasks")

class RankedProduct(BaseModel):
    rank: int = Field(description="Overall ranking position")
    product_name: str = Field(description="Only the specific submodel/series name (e.g., 'STD800', 'SMV800') - just the short model identifier, not full descriptions")
    vendor: str = Field(description="Vendor name")
    model_family: str = Field(default="", description="Model family/series name (e.g., '3051C', 'STD800') for more specific image searches")

    overall_score: int | float = Field(description="Overall score 0-100")
    requirements_match: bool = Field(description="Whether the product meets ALL critical/mandatory requirements (True) or has fundamental gaps (False)")
    key_strengths: str = Field(description="Detailed parameter-by-parameter analysis of key strengths showing user requirement vs product specification and basis for match")
    concerns: str = Field(description="Detailed parameter-by-parameter analysis of potential concerns, limitations, or verification needs")

class OverallRanking(BaseModel):
    ranked_products: list[RankedProduct] = Field(description="All products ranked by suitability")

class ComparisonRow(BaseModel):
    vendor: str
    product_name: str
    model_family: str = ""
    values: dict[str, str | None] = Field(default_factory=dict, description="Spec key -> extracted value, or null if not found for this product")

class ComparisonTable(BaseModel):
    spec_keys: list[str] = Field(default_factory=list, description="Ordered list of spec field names compared, e.g. schema leaf keys")
    rows: list[ComparisonRow] = Field(default_factory=list, description="One row per analyzed product, values aligned to spec_keys")

class RequirementValidation(BaseModel):
    provided_requirements: dict[str, Any] = Field(description="Requirements that were provided")
    product_type: str = Field(description="Detected product type from user input")
    missing_critical: list[str] = Field(default_factory=list, description="Missing critical requirements")
    is_complete: bool = Field(default=True, description="Whether requirements are complete enough to search")
    validation_message: str = Field(default="", description="Human-readable validation summary")

class SearchRequest(BaseModel):
    user_input: str = Field(description="The user's product search query")
    session_id: str = Field(default="default", description="Conversation session identifier")
    user_id: int | None = Field(default=None, description="Authenticated user ID")
    stream_id: str | None = Field(default=None, description="SSE stream ID for live progress")

class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool
    session_id: str
    ranked_products: list[RankedProduct] = Field(default_factory=list)
    agent_response: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
