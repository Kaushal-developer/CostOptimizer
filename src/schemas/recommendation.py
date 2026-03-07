from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class RecommendationResponse(BaseModel):
    id: int
    resource_id: int
    tenant_id: int
    type: str
    priority: str
    status: str
    title: str
    description: str
    ai_explanation: str | None = None
    current_config: dict[str, Any] | None = None
    recommended_config: dict[str, Any] | None = None
    current_monthly_cost: float
    estimated_monthly_cost: float
    estimated_savings: float
    confidence_score: float
    applied_at: datetime | None = None
    applied_by: int | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RecommendationList(BaseModel):
    items: list[RecommendationResponse]
    total: int
    page: int
    page_size: int


class RecommendationActionRequest(BaseModel):
    action: str = Field(pattern="^(accept|reject|apply)$")


class RecommendationFilter(BaseModel):
    type: str | None = None
    priority: str | None = None
    status: str | None = None
    cloud_account_id: int | None = None


class WhatIfRequest(BaseModel):
    recommendation_ids: list[int] = Field(min_length=1)


class WhatIfResponse(BaseModel):
    total_current_cost: float
    total_estimated_cost: float
    total_savings: float
    savings_percentage: float
    recommendations: list[RecommendationResponse]
