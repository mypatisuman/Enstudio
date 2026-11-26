"""
Auth schemas — Pydantic models for auth request/response shapes.
"""
from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    username: str = Field(description="Username or email")
    password: str = Field(description="User password")


class SignupRequest(BaseModel):
    username: str
    email: str
    password: str
    first_name: str
    last_name: str
    company: str | None = None
    location: str | None = None
    strategy: str | None = None


class AuthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")
    success: bool
    message: str
    user_id: int | None = None
    username: str | None = None
