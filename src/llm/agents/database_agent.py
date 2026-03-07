"""Database optimization agent — RDS rightsizing, Aurora, replicas, backups."""

from __future__ import annotations

from src.llm.agents.base_agent import (
    BaseOptimizationAgent, AgentRecommendation,
)
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import RecommendationType, RecommendationPriority


class DatabaseAgent(BaseOptimizationAgent):
    """Specializes in RDS and database optimization."""

    @property
    def domain(self) -> str:
        return "database"

    @property
    def supported_resource_types(self) -> list[str]:
        return ["rds:instance"]

    def _build_domain_context(self) -> str:
        return (
            "You are a cloud database cost optimization expert. You specialize in:\n"
            "- RDS instance rightsizing based on CPU, memory, and connection metrics\n"
            "- Aurora Serverless v2 migration for variable workloads\n"
            "- Read replica optimization and consolidation\n"
            "- Backup retention and storage optimization\n"
            "- Multi-AZ cost/benefit analysis\n"
            "- Reserved Instance recommendations for databases\n\n"
            "Pricing context:\n"
            "- Multi-AZ doubles the instance cost\n"
            "- Aurora Serverless v2: $0.12/ACU-hour, min 0.5 ACU\n"
            "- RDS Reserved: 30-60% savings over on-demand\n"
            "Provide specific, actionable recommendations."
        )

    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        results: list[AgentRecommendation] = []
        meta = resource.metadata_ or {}
        metric_map = {m.metric_name: m for m in metrics}

        # Multi-AZ for non-production
        multi_az = meta.get("multi_az", False)
        if multi_az and resource.tags:
            env = (resource.tags.get("Environment") or resource.tags.get("env") or "").lower()
            if env in ("dev", "development", "staging", "test", "qa"):
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.RIGHTSIZE,
                    priority=RecommendationPriority.HIGH,
                    title=f"Disable Multi-AZ: {resource.name or resource.resource_id}",
                    description=(
                        f"This {env} database has Multi-AZ enabled, doubling the cost. "
                        f"Non-production databases rarely need high availability failover. "
                        f"Disabling Multi-AZ saves ~50% (${resource.monthly_cost * 0.5:.2f}/mo)."
                    ),
                    estimated_savings_pct=0.5,
                    recommended_config={"multi_az": False},
                    confidence_score=90.0,
                ))

        # Aurora Serverless candidate (variable/low CPU)
        cpu = metric_map.get("cpu_utilization")
        conns = metric_map.get("database_connections")
        if cpu and cpu.max_value > 2 * cpu.avg_value and cpu.avg_value < 30:
            engine = meta.get("engine", "")
            if engine in ("mysql", "postgres", "aurora-mysql", "aurora-postgresql"):
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Aurora Serverless: {resource.name or resource.resource_id}",
                    description=(
                        f"CPU pattern is highly variable (avg {cpu.avg_value:.0f}%, "
                        f"max {cpu.max_value:.0f}%), ideal for Aurora Serverless v2. "
                        f"It auto-scales from 0.5 ACU and you pay only for capacity used. "
                        f"Potential savings: 40-60% for variable workloads."
                    ),
                    estimated_savings_pct=0.45,
                    recommended_config={"target": "aurora_serverless_v2"},
                    confidence_score=70.0,
                ))

        # Long backup retention
        backup_days = meta.get("backup_retention_period", 0)
        if backup_days > 14:
            results.append(AgentRecommendation(
                recommendation_type=RecommendationType.STORAGE_TIER,
                priority=RecommendationPriority.LOW,
                title=f"Review backup retention: {resource.name or resource.resource_id}",
                description=(
                    f"Backup retention is set to {backup_days} days. Backups beyond the "
                    f"free tier (equal to allocated storage) are charged at $0.095/GB-month. "
                    f"Review if {backup_days} days is required for compliance — "
                    f"7-14 days is sufficient for most workloads."
                ),
                estimated_savings_pct=0.05,
                recommended_config={"backup_retention_period": 7},
                confidence_score=55.0,
            ))

        # Publicly accessible warning
        if meta.get("publicly_accessible"):
            results.append(AgentRecommendation(
                recommendation_type=RecommendationType.MODERNIZE,
                priority=RecommendationPriority.HIGH,
                title=f"Disable public access: {resource.name or resource.resource_id}",
                description=(
                    "This database is publicly accessible from the internet. "
                    "Move to a private subnet and use VPC endpoints or bastion hosts "
                    "for access. This is a critical security best practice."
                ),
                estimated_savings_pct=0.0,
                recommended_config={"publicly_accessible": False},
                confidence_score=98.0,
            ))

        return results
