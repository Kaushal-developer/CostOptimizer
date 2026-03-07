"""Compute optimization agent — EC2/VM rightsizing, spot, reserved, ARM, scheduling."""

from __future__ import annotations

from src.llm.agents.base_agent import (
    BaseOptimizationAgent, AgentRecommendation,
)
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import RecommendationType, RecommendationPriority

# Graviton equivalent mappings
GRAVITON_MAP = {
    "t3": "t4g", "t3a": "t4g", "m5": "m6g", "m5a": "m6g",
    "c5": "c7g", "c5a": "c7g", "r5": "r6g", "r5a": "r6g",
    "m6i": "m7g", "c6i": "c7g", "r6i": "r7g",
}

# Instance size ordering for rightsizing
SIZE_ORDER = [
    "nano", "micro", "small", "medium", "large",
    "xlarge", "2xlarge", "4xlarge", "8xlarge", "12xlarge", "16xlarge", "24xlarge",
]

# Approximate monthly pricing for specific recommendations
PRICING: dict[str, float] = {
    "t3.nano": 3.80, "t3.micro": 7.59, "t3.small": 15.18, "t3.medium": 30.37,
    "t3.large": 60.74, "t3.xlarge": 121.47, "t3.2xlarge": 242.94,
    "t4g.nano": 3.07, "t4g.micro": 6.13, "t4g.small": 12.26, "t4g.medium": 24.53,
    "t4g.large": 49.06, "t4g.xlarge": 98.11, "t4g.2xlarge": 196.22,
    "m5.large": 70.08, "m5.xlarge": 140.16, "m5.2xlarge": 280.32, "m5.4xlarge": 560.64,
    "m6g.large": 56.21, "m6g.xlarge": 112.42, "m6g.2xlarge": 224.84,
    "c5.large": 62.05, "c5.xlarge": 124.10, "c5.2xlarge": 248.20,
    "c7g.large": 52.87, "c7g.xlarge": 105.74, "c7g.2xlarge": 211.48,
    "r5.large": 91.98, "r5.xlarge": 183.96, "r5.2xlarge": 367.92,
    "r6g.large": 73.58, "r6g.xlarge": 147.17, "r6g.2xlarge": 294.34,
}


def _suggest_downsize(instance_type: str, cpu_avg: float, cpu_max: float) -> str | None:
    """Suggest a specific smaller instance based on CPU usage pattern."""
    if not instance_type or "." not in instance_type:
        return None
    family, size = instance_type.rsplit(".", 1)
    if size not in SIZE_ORDER:
        return None
    idx = SIZE_ORDER.index(size)
    if idx == 0:
        return None
    # Determine step-down based on utilization
    if cpu_avg < 5:
        target_idx = max(0, idx - 3)
    elif cpu_avg < 10:
        target_idx = max(0, idx - 2)
    elif cpu_max < 40:
        target_idx = max(0, idx - 1)
    else:
        return None
    return f"{family}.{SIZE_ORDER[target_idx]}"


class ComputeAgent(BaseOptimizationAgent):
    """Specializes in EC2/VM compute optimization."""

    @property
    def domain(self) -> str:
        return "compute"

    @property
    def supported_resource_types(self) -> list[str]:
        return ["ec2:instance"]

    def _build_domain_context(self) -> str:
        return (
            "You are a cloud compute cost optimization expert. You specialize in:\n"
            "- EC2 instance rightsizing based on CPU/memory/network utilization\n"
            "- Spot instance conversion for fault-tolerant workloads\n"
            "- Reserved Instance and Savings Plan recommendations\n"
            "- ARM/Graviton migration (20% cheaper, better performance)\n"
            "- Instance scheduling for non-production environments\n"
            "- Identifying idle and zombie instances\n\n"
            "AWS instance pricing context:\n"
            "- Graviton instances are ~20% cheaper than x86 equivalents\n"
            "- Spot instances save 60-90% but can be interrupted\n"
            "- 1-year Savings Plans save ~35-40% over on-demand\n"
            "- Stopping instances saves compute but EBS costs continue\n"
            "Provide specific, actionable recommendations with estimated savings."
        )

    async def analyze(
        self, resource: Resource, metrics: list[ResourceMetric]
    ) -> list[AgentRecommendation]:
        results: list[AgentRecommendation] = []
        meta = resource.metadata_ or {}
        metric_map = {m.metric_name: m for m in metrics}
        itype = resource.instance_type or ""

        # ARM/Graviton migration check
        arch = meta.get("architecture", "x86_64")
        if arch == "x86_64" and itype:
            family = itype.split(".")[0]
            if family in GRAVITON_MAP:
                arm_family = GRAVITON_MAP[family]
                arm_type = itype.replace(family, arm_family, 1)
                current_price = PRICING.get(itype, resource.monthly_cost)
                arm_price = PRICING.get(arm_type, current_price * 0.8)
                savings = current_price - arm_price
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.ARM_MIGRATE,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Migrate to Graviton: {itype} → {arm_type}",
                    description=(
                        f"Migrate {itype} (x86_64) to {arm_type} (ARM/Graviton). "
                        f"Graviton offers ~20% cost savings with equal or better performance. "
                        f"Estimated savings: ${savings:.2f}/mo (${current_price:.2f} → ${arm_price:.2f}). "
                        f"Most containerized and interpreted language workloads "
                        f"(Python, Node.js, Java) work seamlessly on ARM."
                    ),
                    estimated_savings_pct=0.2,
                    recommended_config={
                        "current_type": itype,
                        "recommended_type": arm_type,
                        "architecture": "arm64",
                        "current_monthly": round(current_price, 2),
                        "estimated_monthly": round(arm_price, 2),
                    },
                    confidence_score=75.0,
                ))

        # Specific rightsizing with exact target instance
        cpu = metric_map.get("cpu_utilization")
        if cpu and cpu.avg_value < 20 and itype:
            target = _suggest_downsize(itype, cpu.avg_value, cpu.max_value)
            if target:
                current_price = PRICING.get(itype, resource.monthly_cost)
                target_price = PRICING.get(target, current_price * 0.5)
                savings = current_price - target_price
                if savings > 0:
                    results.append(AgentRecommendation(
                        recommendation_type=RecommendationType.RIGHTSIZE,
                        priority=RecommendationPriority.HIGH,
                        title=f"Rightsize: {itype} → {target}",
                        description=(
                            f"CPU utilization is only {cpu.avg_value:.1f}% avg / {cpu.max_value:.1f}% max "
                            f"over {cpu.period_days} days. This {itype} is significantly overprovisioned. "
                            f"Downsize to {target} to save ${savings:.2f}/mo "
                            f"(${current_price:.2f} → ${target_price:.2f}). "
                            f"Annual savings: ${savings * 12:.2f}."
                        ),
                        estimated_savings_pct=round(savings / current_price, 2) if current_price > 0 else 0.4,
                        recommended_config={
                            "current_type": itype,
                            "recommended_type": target,
                            "current_monthly": round(current_price, 2),
                            "estimated_monthly": round(target_price, 2),
                        },
                        confidence_score=85.0,
                    ))

        # On-Demand → Savings Plan / Reserved Instance
        purchase_type = meta.get("purchase_type", "on-demand")
        if purchase_type == "on-demand" and cpu and cpu.avg_value > 20 and resource.monthly_cost > 50:
            savings_1yr = resource.monthly_cost * 0.35
            savings_3yr = resource.monthly_cost * 0.60
            results.append(AgentRecommendation(
                recommendation_type=RecommendationType.SAVINGS_PLAN,
                priority=RecommendationPriority.MEDIUM,
                title=f"On-Demand → Savings Plan: {resource.name or resource.resource_id}",
                description=(
                    f"This {itype} is running On-Demand at ${resource.monthly_cost:.2f}/mo "
                    f"with steady utilization ({cpu.avg_value:.0f}% avg CPU). "
                    f"Switch to a Compute Savings Plan:\n"
                    f"- 1-year commitment: ${resource.monthly_cost - savings_1yr:.2f}/mo (save ${savings_1yr:.2f}/mo)\n"
                    f"- 3-year commitment: ${resource.monthly_cost - savings_3yr:.2f}/mo (save ${savings_3yr:.2f}/mo)\n"
                    f"Savings Plans apply flexibly across instance families, sizes, and regions."
                ),
                estimated_savings_pct=0.35,
                recommended_config={
                    "current_pricing": "on-demand",
                    "recommended_pricing": "compute_savings_plan",
                    "current_monthly": round(resource.monthly_cost, 2),
                    "savings_1yr": round(savings_1yr, 2),
                    "savings_3yr": round(savings_3yr, 2),
                },
                confidence_score=80.0,
            ))

        # Scheduling for non-production
        if resource.tags:
            env = (resource.tags.get("Environment") or resource.tags.get("env") or "").lower()
            state = meta.get("state", "")
            if env in ("dev", "development", "staging", "test", "qa") and state == "running":
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.LOW,
                    title=f"Schedule auto-stop: {resource.name or resource.resource_id}",
                    description=(
                        f"This {env} {itype} runs 24/7 but likely only needs business hours. "
                        f"Implement Instance Scheduler to stop outside work hours "
                        f"(e.g., 7AM-7PM weekdays). Saves ~65% on compute "
                        f"(${resource.monthly_cost * 0.65:.2f}/mo)."
                    ),
                    estimated_savings_pct=0.65,
                    recommended_config={"schedule": "business_hours", "stop_outside": True},
                    confidence_score=60.0,
                ))

        # LLM-enhanced analysis for complex cases
        if self.llm and metrics:
            ctx = self._format_resource_context(resource, metrics)
            llm_insight = await self._ask_llm(
                f"Analyze this EC2 instance for additional optimization opportunities "
                f"beyond basic rightsizing and spot conversion:\n\n{ctx}\n\n"
                f"Focus on: instance family modernization, EBS optimization, "
                f"network optimization, or workload migration opportunities. "
                f"Respond with a single concise recommendation or 'No additional optimizations found.'"
            )
            if llm_insight and "no additional" not in llm_insight.lower():
                results.append(AgentRecommendation(
                    recommendation_type=RecommendationType.MODERNIZE,
                    priority=RecommendationPriority.LOW,
                    title=f"AI insight: {resource.name or resource.resource_id}",
                    description=llm_insight[:500],
                    estimated_savings_pct=0.15,
                    confidence_score=55.0,
                ))

        return results
