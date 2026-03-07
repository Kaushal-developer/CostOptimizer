"""Base classes for cloud resource collectors."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date


@dataclass
class CollectedMetric:
    """A single metric observation for a cloud resource."""

    metric_name: str  # cpu_utilization, memory_utilization, network_in, network_out, disk_iops
    avg_value: float
    max_value: float
    min_value: float
    p95_value: float | None = None
    period_days: int = 30


@dataclass
class CollectedResource:
    """Normalized representation of a cloud resource collected from any provider."""

    resource_id: str
    resource_type: str  # maps to ResourceType enum value
    provider_resource_type: str  # e.g. "ec2:instance", "rds:instance"
    region: str
    name: str | None = None
    instance_type: str | None = None
    vcpus: int | None = None
    memory_gb: float | None = None
    storage_gb: float | None = None
    monthly_cost: float = 0.0
    tags: dict | None = None
    metadata: dict | None = None
    metrics: list[CollectedMetric] = field(default_factory=list)


class BaseCollector(ABC):
    """Abstract base for all cloud provider collectors."""

    @abstractmethod
    async def validate_credentials(self) -> bool:
        """Return True if the configured credentials are valid and usable."""
        ...

    @abstractmethod
    async def collect_resources(self) -> list[CollectedResource]:
        """Discover and return all resources across enabled regions."""
        ...

    @abstractmethod
    async def collect_billing(
        self, start_date: date, end_date: date
    ) -> dict:
        """Return billing/cost data for the given date range."""
        ...
