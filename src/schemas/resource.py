from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


class ResourceMetricResponse(BaseModel):
    id: int
    metric_name: str
    avg_value: float
    max_value: float
    min_value: float
    p95_value: float | None = None
    period_days: int
    collected_at: datetime

    model_config = {"from_attributes": True}


class ResourceMetricHistoryPoint(BaseModel):
    collected_at: datetime
    avg_value: float
    max_value: float
    min_value: float
    p95_value: float | None = None


class ResourceMetricHistory(BaseModel):
    metric_name: str
    period_days: int
    datapoints: list[ResourceMetricHistoryPoint]


class ResourceResponse(BaseModel):
    id: int
    cloud_account_id: int
    resource_id: str
    resource_type: str
    provider_resource_type: str
    region: str
    status: str
    name: str | None = None
    instance_type: str | None = None
    vcpus: int | None = None
    memory_gb: float | None = None
    storage_gb: float | None = None
    monthly_cost: float
    currency: str = "USD"
    tags: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = Field(None, alias="metadata_")
    last_seen_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True, "populate_by_name": True}


class ResourceDetail(ResourceResponse):
    metrics: list[ResourceMetricResponse] = []


class ResourceList(BaseModel):
    items: list[ResourceResponse]
    total: int
    page: int
    page_size: int


class ResourceFilter(BaseModel):
    resource_type: str | None = None
    status: str | None = None
    region: str | None = None
    cloud_account_id: int | None = None
    min_cost: float | None = None
    max_cost: float | None = None
