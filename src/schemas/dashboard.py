from datetime import datetime
from typing import Any
from pydantic import BaseModel


class CostBreakdown(BaseModel):
    by_provider: dict[str, float] = {}
    by_resource_type: dict[str, float] = {}
    by_region: dict[str, float] = {}


class SavingsOverview(BaseModel):
    total_spend: float
    potential_savings: float
    realized_savings: float
    optimization_score: float
    savings_by_category: dict[str, float] = {}
    savings_by_service: dict[str, float] = {}
    period_start: datetime | None = None
    period_end: datetime | None = None
    executive_summary: str | None = None


class DashboardSummary(BaseModel):
    total_cloud_accounts: int
    total_resources: int
    total_monthly_spend: float
    total_potential_savings: float
    open_recommendations: int
    critical_recommendations: int
    optimization_score: float
    cost_breakdown: CostBreakdown
    top_savings_opportunities: list[dict[str, Any]] = []


class NLQueryRequest(BaseModel):
    query: str


class NLQueryResponse(BaseModel):
    query: str
    answer: str
    data: dict[str, Any] | None = None
    visualization_hint: str | None = None
