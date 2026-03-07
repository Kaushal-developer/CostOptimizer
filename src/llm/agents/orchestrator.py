"""
Orchestrator — routes resources to domain-specific agents and merges results.
"""

from __future__ import annotations

import structlog
from typing import Any

from src.llm.agents.base_agent import AgentRecommendation, BaseOptimizationAgent
from src.llm.agents.compute_agent import ComputeAgent
from src.llm.agents.storage_agent import StorageAgent
from src.llm.agents.database_agent import DatabaseAgent
from src.llm.agents.network_agent import NetworkAgent
from src.models.resource import Resource, ResourceMetric

logger = structlog.get_logger(__name__)


class AgentOrchestrator:
    """Routes resources to appropriate domain agents and collects recommendations."""

    def __init__(self, llm_client: Any | None = None):
        self._agents: list[BaseOptimizationAgent] = [
            ComputeAgent(llm_client),
            StorageAgent(llm_client),
            DatabaseAgent(llm_client),
            NetworkAgent(llm_client),
        ]

    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        """Run all applicable agents on a resource and return merged recommendations."""
        all_recs: list[AgentRecommendation] = []

        for agent in self._agents:
            if agent.can_handle(resource):
                try:
                    recs = await agent.analyze(resource, metrics)
                    all_recs.extend(recs)
                    if recs:
                        logger.debug(
                            "agent_recommendations",
                            agent=agent.domain,
                            resource=resource.resource_id,
                            count=len(recs),
                        )
                except Exception as exc:
                    logger.warning(
                        "agent_failed",
                        agent=agent.domain,
                        resource=resource.resource_id,
                        error=str(exc),
                    )

        return all_recs
