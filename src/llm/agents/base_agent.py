"""Base class for domain-specific optimization agents."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import RecommendationType, RecommendationPriority


@dataclass
class AgentRecommendation:
    """A recommendation produced by an optimization agent."""
    recommendation_type: RecommendationType
    priority: RecommendationPriority
    title: str
    description: str
    estimated_savings_pct: float
    recommended_config: dict | None = None
    confidence_score: float = 70.0


class BaseOptimizationAgent(ABC):
    """Abstract base for domain-specific optimization agents.

    Each agent specializes in a resource domain (compute, storage, database, network)
    and uses an LLM with domain-specific context to generate deeper recommendations
    beyond what the rule engine can produce.
    """

    def __init__(self, llm_client: Any | None = None):
        self.llm = llm_client
        self._domain_context = self._build_domain_context()

    @property
    @abstractmethod
    def domain(self) -> str:
        """Return the domain name (e.g., 'compute', 'storage')."""
        ...

    @property
    @abstractmethod
    def supported_resource_types(self) -> list[str]:
        """Return list of provider_resource_type values this agent handles."""
        ...

    @abstractmethod
    def _build_domain_context(self) -> str:
        """Build the domain-specific system prompt context."""
        ...

    @abstractmethod
    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        """Analyze a resource and return optimization recommendations."""
        ...

    def can_handle(self, resource: Resource) -> bool:
        """Check if this agent can handle the given resource."""
        return resource.provider_resource_type in self.supported_resource_types

    async def _ask_llm(self, prompt: str) -> str | None:
        """Query the LLM with domain context."""
        if not self.llm:
            return None
        return await self.llm.generate(
            prompt=prompt,
            system_prompt=self._domain_context,
            max_tokens=512,
        )

    def _format_resource_context(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> str:
        """Format resource data into a prompt context string."""
        lines = [
            f"Resource ID: {resource.resource_id}",
            f"Type: {resource.provider_resource_type}",
            f"Instance Type: {resource.instance_type or 'N/A'}",
            f"Region: {resource.region}",
            f"Monthly Cost: ${resource.monthly_cost:.2f}",
            f"Status: {resource.status.value}",
        ]
        if resource.vcpus:
            lines.append(f"vCPUs: {resource.vcpus}")
        if resource.memory_gb:
            lines.append(f"Memory: {resource.memory_gb}GB")
        if resource.storage_gb:
            lines.append(f"Storage: {resource.storage_gb}GB")
        if resource.tags:
            lines.append(f"Tags: {resource.tags}")
        if resource.metadata_:
            lines.append(f"Metadata: {resource.metadata_}")

        if metrics:
            lines.append("\nMetrics (30-day):")
            for m in metrics:
                lines.append(
                    f"  {m.metric_name}: avg={m.avg_value:.2f}, max={m.max_value:.2f}, "
                    f"min={m.min_value:.2f}, p95={m.p95_value:.2f}" if m.p95_value
                    else f"  {m.metric_name}: avg={m.avg_value:.2f}, max={m.max_value:.2f}, min={m.min_value:.2f}"
                )
        return "\n".join(lines)
