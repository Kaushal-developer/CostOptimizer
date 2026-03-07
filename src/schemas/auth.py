from datetime import datetime
from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshRequest(BaseModel):
    refresh_token: str


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=255)
    tenant_name: str = Field(min_length=1, max_length=255)

    model_config = {"json_schema_extra": {"examples": [{"email": "user@example.com", "password": "securepass123", "full_name": "John Doe", "tenant_name": "Acme Corp"}]}}


class UserResponse(BaseModel):
    id: int
    tenant_id: int
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
