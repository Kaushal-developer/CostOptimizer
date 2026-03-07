"""
Infrastructure cost reduction analyzer.

Detects opportunities for:
- ARM/Graviton migration
- gp2 → gp3 EBS volume upgrades
- Serverless migration candidates
- Reserved Instance / Savings Plan recommendations
- Regional pricing optimization
"""

from __future__ import annotations

from src.models.resource import Resource, ResourceMetric, ResourceType
from src.models.recommendation import RecommendationType, RecommendationPriority
from src.engine.rule_engine import RuleResult

# ARM/Graviton instance family mappings
GRAVITON_MAP: dict[str, str] = {
    "t3": "t4g", "t3a": "t4g",
    "m5": "m6g", "m5a": "m6g", "m5n": "m6gn",
    "c5": "c7g", "c5a": "c7g", "c5n": "c7gn",
    "r5": "r6g", "r5a": "r6g", "r5n": "r6gn",
    "m6i": "m7g", "c6i": "c7g", "r6i": "r7g",
}

# Relative pricing for regional comparison (us-east-1 = 1.0)
REGION_PRICE_FACTOR: dict[str, float] = {
    "us-east-1": 1.0, "us-east-2": 1.0, "us-west-2": 1.0,
    "us-west-1": 1.1,
    "eu-west-1": 1.08, "eu-central-1": 1.12,
    "ap-southeast-1": 1.05, "ap-northeast-1": 1.15,
    "ap-south-1": 0.85,  # Mumbai is cheaper
    "sa-east-1": 1.40,
}


class InfraAnalyzer:
    """Analyze infrastructure for cost reduction opportunities."""

    def evaluate(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[RuleResult]:
        """Run all infrastructure analysis rules on a resource."""
        results: list[RuleResult] = []
        metric_map = {m.metric_name: m for m in metrics}

        if resource.resource_type == ResourceType.COMPUTE:
            results.extend(self._check_arm_migration(resource))
            results.extend(self._check_serverless(resource, metric_map))
            results.extend(self._check_savings_plan(resource, metric_map))
            results.extend(self._check_region_pricing(resource))

        if resource.resource_type == ResourceType.VOLUME:
            results.extend(self._check_gp3_upgrade(resource))

        return [r for r in results if r.triggered]

    def _check_arm_migration(self, resource: Resource) -> list[RuleResult]:
        """Check if an x86 instance can migrate to ARM/Graviton."""
        meta = resource.metadata_ or {}
        arch = meta.get("architecture", "x86_64")
        itype = resource.instance_type or ""

        if arch != "x86_64" or not itype:
            return []

        family = itype.split(".")[0]
        if family not in GRAVITON_MAP:
            return []

        arm_family = GRAVITON_MAP[family]
        arm_type = itype.replace(family, arm_family, 1)
        savings_pct = 0.20
        savings = resource.monthly_cost * savings_pct

        return [RuleResult(
            triggered=True,
            recommendation_type=RecommendationType.ARM_MIGRATE,
            priority=RecommendationPriority.MEDIUM,
            title=f"Graviton migration: {resource.name or resource.resource_id}",
            description=(
                f"Migrate {itype} (x86_64) to {arm_type} (ARM/Graviton) for ~20% savings. "
                f"Graviton provides equal or better performance for most workloads. "
                f"Estimated savings: ${savings:.2f}/month (${savings * 12:.2f}/year). "
                f"Verify application compatibility — most containerized and interpreted "
                f"language workloads (Python, Node.js, Java) work seamlessly."
            ),
            estimated_savings_pct=savings_pct,
            recommended_config={
                "current_type": itype,
                "recommended_type": arm_type,
                "architecture": "arm64",
            },
        )]

    def _check_gp3_upgrade(self, resource: Resource) -> list[RuleResult]:
        """Check if a gp2 volume should upgrade to gp3."""
        meta = resource.metadata_ or {}
        vol_type = meta.get("volume_type", "")

        if vol_type != "gp2" or not resource.storage_gb:
            return []

        gp2_cost = resource.storage_gb * 0.10
        gp3_cost = resource.storage_gb * 0.08
        savings = gp2_cost - gp3_cost

        return [RuleResult(
            triggered=True,
            recommendation_type=RecommendationType.GP3_UPGRADE,
            priority=RecommendationPriority.HIGH,
            title=f"Upgrade to gp3: {resource.name or resource.resource_id}",
            description=(
                f"This {resource.storage_gb}GB gp2 volume should be upgraded to gp3. "
                f"gp3 is always cheaper ($0.08/GB vs $0.10/GB) with better baseline "
                f"performance (3,000 IOPS + 125 MB/s throughput included). "
                f"Migration is online via EBS ModifyVolume — zero downtime. "
                f"Savings: ${savings:.2f}/month (${savings * 12:.2f}/year)."
            ),
            estimated_savings_pct=0.20,
            recommended_config={
                "current_type": "gp2",
                "recommended_type": "gp3",
                "baseline_iops": 3000,
                "baseline_throughput_mbps": 125,
            },
        )]

    def _check_serverless(
        self, resource: Resource, metrics: dict[str, ResourceMetric]
    ) -> list[RuleResult]:
        """Check if an instance is a candidate for serverless migration."""
        cpu = metrics.get("cpu_utilization")
        if not cpu:
            return []

        # Serverless candidates: low average CPU with high variance (bursty)
        if cpu.avg_value < 15 and cpu.max_value > 2 * cpu.avg_value:
            itype = resource.instance_type or ""
            # Only suggest for smaller instances (serverless makes less sense for large)
            if any(itype.startswith(f) for f in ["t3.", "t4g.", "m5.large", "m6g.large"]):
                est_serverless_cost = resource.monthly_cost * 0.2
                savings = resource.monthly_cost - est_serverless_cost

                return [RuleResult(
                    triggered=True,
                    recommendation_type=RecommendationType.SERVERLESS,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Serverless candidate: {resource.name or resource.resource_id}",
                    description=(
                        f"This {itype} has bursty CPU (avg {cpu.avg_value:.0f}%, "
                        f"max {cpu.max_value:.0f}%) — ideal for serverless. "
                        f"AWS Lambda + API Gateway or Fargate with autoscaling min=0 "
                        f"could reduce costs to ~${est_serverless_cost:.2f}/month "
                        f"(saving ${savings:.2f}/month). Pay only for actual compute time."
                    ),
                    estimated_savings_pct=0.80,
                    recommended_config={
                        "target": "aws_lambda_or_fargate",
                        "estimated_monthly_cost": round(est_serverless_cost, 2),
                    },
                )]
        return []

    def _check_savings_plan(
        self, resource: Resource, metrics: dict[str, ResourceMetric]
    ) -> list[RuleResult]:
        """Check if an on-demand instance should use Savings Plans."""
        meta = resource.metadata_ or {}
        purchase_type = meta.get("purchase_type", "on-demand")

        if purchase_type != "on-demand" or resource.monthly_cost < 30:
            return []

        cpu = metrics.get("cpu_utilization")
        # Only recommend for steady-state workloads
        if not cpu or cpu.avg_value < 20:
            return []

        savings_1yr = resource.monthly_cost * 0.35
        savings_3yr = resource.monthly_cost * 0.60

        return [RuleResult(
            triggered=True,
            recommendation_type=RecommendationType.SAVINGS_PLAN,
            priority=RecommendationPriority.MEDIUM,
            title=f"Savings Plan: {resource.name or resource.resource_id}",
            description=(
                f"This on-demand {resource.instance_type} has steady utilization "
                f"({cpu.avg_value:.0f}% avg CPU over {cpu.period_days}d). "
                f"Commit with a Compute Savings Plan:\n"
                f"- 1-year: save ~${savings_1yr:.2f}/mo (${savings_1yr * 12:.2f}/yr)\n"
                f"- 3-year: save ~${savings_3yr:.2f}/mo (${savings_3yr * 12:.2f}/yr)\n"
                f"Savings Plans apply flexibly across instance families and regions."
            ),
            estimated_savings_pct=0.35,
            recommended_config={
                "commitment_type": "compute_savings_plan",
                "term_1yr_savings": round(savings_1yr, 2),
                "term_3yr_savings": round(savings_3yr, 2),
            },
        )]

    def _check_region_pricing(self, resource: Resource) -> list[RuleResult]:
        """Check if the resource is in an expensive region."""
        region = resource.region
        factor = REGION_PRICE_FACTOR.get(region, 1.0)

        if factor <= 1.05 or resource.monthly_cost < 50:
            return []

        # Find cheapest equivalent region
        cheapest_region = min(REGION_PRICE_FACTOR, key=REGION_PRICE_FACTOR.get)
        cheapest_factor = REGION_PRICE_FACTOR[cheapest_region]
        potential_savings = resource.monthly_cost * (1 - cheapest_factor / factor)

        if potential_savings < 5:
            return []

        return [RuleResult(
            triggered=True,
            recommendation_type=RecommendationType.REGION_MOVE,
            priority=RecommendationPriority.LOW,
            title=f"Consider cheaper region: {resource.name or resource.resource_id}",
            description=(
                f"This resource is in {region} (price factor: {factor:.2f}x). "
                f"Moving to {cheapest_region} ({cheapest_factor:.2f}x) could save "
                f"~${potential_savings:.2f}/month. Consider latency requirements and "
                f"data residency regulations before migrating."
            ),
            estimated_savings_pct=round(potential_savings / resource.monthly_cost, 2),
            recommended_config={
                "current_region": region,
                "recommended_region": cheapest_region,
            },
        )]
