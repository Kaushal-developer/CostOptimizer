"""Storage optimization agent — S3 tiering, EBS gp2→gp3, snapshot cleanup."""

from __future__ import annotations

from src.llm.agents.base_agent import (
    BaseOptimizationAgent, AgentRecommendation,
)
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import RecommendationType, RecommendationPriority


class StorageAgent(BaseOptimizationAgent):
    """Specializes in S3 and EBS storage optimization."""

    @property
    def domain(self) -> str:
        return "storage"

    @property
    def supported_resource_types(self) -> list[str]:
        return ["s3:bucket", "ebs:volume", "ebs:snapshot"]

    def _build_domain_context(self) -> str:
        return (
            "You are a cloud storage cost optimization expert. You specialize in:\n"
            "- S3 lifecycle policies and storage class tiering\n"
            "- EBS volume type optimization (gp2→gp3 is always cheaper)\n"
            "- Snapshot retention and cleanup policies\n"
            "- Data compression and deduplication strategies\n\n"
            "Pricing context:\n"
            "- S3 Standard: $0.023/GB, IA: $0.0125/GB, Glacier: $0.004/GB\n"
            "- EBS gp2: $0.10/GB, gp3: $0.08/GB (20% cheaper + better baseline IOPS)\n"
            "- Snapshots: $0.05/GB\n"
            "Provide specific, actionable recommendations with estimated savings."
        )

    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        results: list[AgentRecommendation] = []
        meta = resource.metadata_ or {}

        # EBS gp2 → gp3 migration (always beneficial)
        if resource.provider_resource_type == "ebs:volume":
            vol_type = meta.get("volume_type", "")
            if vol_type == "gp2" and resource.storage_gb:
                gp2_cost = resource.storage_gb * 0.10
                gp3_cost = resource.storage_gb * 0.08
                savings = gp2_cost - gp3_cost
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.HIGH,
                    title=f"Upgrade to gp3: {resource.name or resource.resource_id}",
                    description=(
                        f"Migrate this {resource.storage_gb}GB gp2 volume to gp3. "
                        f"gp3 is always cheaper ($0.08/GB vs $0.10/GB) with better "
                        f"baseline performance (3,000 IOPS vs {min(int(resource.storage_gb * 3), 16000)} IOPS). "
                        f"Migration is online via EBS Modify Volume with zero downtime. "
                        f"Saves ${savings:.2f}/month."
                    ),
                    estimated_savings_pct=0.2,
                    recommended_config={"volume_type": "gp3"},
                    confidence_score=95.0,
                ))

            # Check for overprovisioned io1/io2 volumes
            if vol_type in ("io1", "io2"):
                provisioned_iops = meta.get("iops", 0)
                metric_map = {m.metric_name: m for m in metrics}
                iops_metric = metric_map.get("disk_iops")
                if iops_metric and provisioned_iops > 0:
                    usage_pct = (iops_metric.max_value / provisioned_iops) * 100
                    if usage_pct < 30:
                        results.append(AgentRecommendation(
                            recommendation_type=RecommendationType.RIGHTSIZE,
                            priority=RecommendationPriority.MEDIUM,
                            title=f"Overprovisioned IOPS: {resource.name or resource.resource_id}",
                            description=(
                                f"This {vol_type} volume has {provisioned_iops} provisioned IOPS "
                                f"but only uses {iops_metric.max_value:.0f} max ({usage_pct:.0f}%). "
                                f"Consider reducing IOPS or switching to gp3 with custom IOPS."
                            ),
                            estimated_savings_pct=0.4,
                            confidence_score=75.0,
                        ))

        # S3 versioning cost check
        if resource.provider_resource_type == "s3:bucket":
            versioning = meta.get("versioning", "Disabled")
            encryption = meta.get("encryption", "none")

            if versioning == "Enabled":
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.STORAGE_TIER,
                    priority=RecommendationPriority.LOW,
                    title=f"Review versioning costs: {resource.name}",
                    description=(
                        "S3 versioning is enabled. Old versions accumulate silently and "
                        "increase storage costs. Set lifecycle rules to expire noncurrent "
                        "versions after 30-90 days and delete incomplete multipart uploads."
                    ),
                    estimated_savings_pct=0.2,
                    recommended_config={"lifecycle_rule": "expire_noncurrent_30d"},
                    confidence_score=60.0,
                ))

            if encryption == "none":
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.LOW,
                    title=f"Enable encryption: {resource.name}",
                    description=(
                        "This bucket has no server-side encryption. Enable SSE-S3 "
                        "(free) or SSE-KMS for compliance. This is a security best "
                        "practice with zero cost impact."
                    ),
                    estimated_savings_pct=0.0,
                    recommended_config={"encryption": "SSE-S3"},
                    confidence_score=95.0,
                ))

        return results
