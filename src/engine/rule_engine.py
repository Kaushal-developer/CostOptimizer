"""
Rule-based optimization engine.
Applies deterministic rules to detect waste, idle resources, and optimization opportunities.
"""

from dataclasses import dataclass
from src.models.resource import Resource, ResourceMetric, ResourceType, ResourceStatus
from src.models.recommendation import RecommendationType, RecommendationPriority
from src.core.logging import logger


@dataclass
class RuleResult:
    triggered: bool
    recommendation_type: RecommendationType | None = None
    priority: RecommendationPriority = RecommendationPriority.MEDIUM
    title: str = ""
    description: str = ""
    estimated_savings_pct: float = 0.0
    recommended_config: dict | None = None


# Instance size ordering within a family (smallest to largest)
INSTANCE_SIZE_ORDER = [
    "nano", "micro", "small", "medium", "large",
    "xlarge", "2xlarge", "4xlarge", "8xlarge", "12xlarge", "16xlarge", "24xlarge",
]

# Approximate monthly on-demand pricing (us-east-1) for rightsizing estimation
INSTANCE_PRICING: dict[str, float] = {
    "t3.nano": 3.80, "t3.micro": 7.59, "t3.small": 15.18, "t3.medium": 30.37,
    "t3.large": 60.74, "t3.xlarge": 121.47, "t3.2xlarge": 242.94,
    "t3a.nano": 3.42, "t3a.micro": 6.84, "t3a.small": 13.68, "t3a.medium": 27.36,
    "t3a.large": 54.72, "t3a.xlarge": 109.44, "t3a.2xlarge": 218.88,
    "t4g.nano": 3.07, "t4g.micro": 6.13, "t4g.small": 12.26, "t4g.medium": 24.53,
    "t4g.large": 49.06, "t4g.xlarge": 98.11, "t4g.2xlarge": 196.22,
    "m5.large": 70.08, "m5.xlarge": 140.16, "m5.2xlarge": 280.32, "m5.4xlarge": 560.64,
    "m5.8xlarge": 1121.28, "m5.12xlarge": 1681.92, "m5.16xlarge": 2242.56, "m5.24xlarge": 3363.84,
    "m6i.large": 69.35, "m6i.xlarge": 138.70, "m6i.2xlarge": 277.40,
    "m6g.large": 56.21, "m6g.xlarge": 112.42, "m6g.2xlarge": 224.84,
    "c5.large": 62.05, "c5.xlarge": 124.10, "c5.2xlarge": 248.20, "c5.4xlarge": 496.40,
    "c6i.large": 61.32, "c6i.xlarge": 122.64, "c6i.2xlarge": 245.28,
    "c7g.large": 52.87, "c7g.xlarge": 105.74, "c7g.2xlarge": 211.48,
    "r5.large": 91.98, "r5.xlarge": 183.96, "r5.2xlarge": 367.92,
    "r6g.large": 73.58, "r6g.xlarge": 147.17, "r6g.2xlarge": 294.34,
}


def _get_downsize_target(instance_type: str, cpu_avg: float) -> str | None:
    """Suggest a specific smaller instance type based on CPU usage."""
    if not instance_type or "." not in instance_type:
        return None

    family, size = instance_type.rsplit(".", 1)
    if size not in INSTANCE_SIZE_ORDER:
        return None

    current_idx = INSTANCE_SIZE_ORDER.index(size)
    if current_idx == 0:
        return None  # Already smallest

    # Determine how many sizes to drop based on CPU usage
    if cpu_avg < 5:
        steps_down = min(3, current_idx)  # Aggressive: drop 3 sizes
    elif cpu_avg < 10:
        steps_down = min(2, current_idx)  # Moderate: drop 2 sizes
    elif cpu_avg < 20:
        steps_down = 1  # Conservative: drop 1 size
    else:
        return None

    target_idx = current_idx - steps_down
    target_size = INSTANCE_SIZE_ORDER[target_idx]
    target_type = f"{family}.{target_size}"
    return target_type


class RuleEngine:
    """Evaluates resources against optimization rules."""

    def evaluate(self, resource: Resource, metrics: list[ResourceMetric]) -> list[RuleResult]:
        results = []
        metric_map = {m.metric_name: m for m in metrics}

        if resource.resource_type == ResourceType.COMPUTE:
            results.extend(self._evaluate_compute(resource, metric_map))
        elif resource.resource_type == ResourceType.DATABASE:
            results.extend(self._evaluate_database(resource, metric_map))
        elif resource.resource_type == ResourceType.VOLUME:
            results.extend(self._evaluate_volume(resource, metric_map))
        elif resource.resource_type == ResourceType.SNAPSHOT:
            results.extend(self._evaluate_snapshot(resource))
        elif resource.resource_type == ResourceType.IP_ADDRESS:
            results.extend(self._evaluate_ip(resource, metric_map))
        elif resource.resource_type == ResourceType.STORAGE:
            results.extend(self._evaluate_storage(resource, metric_map))
        elif resource.resource_type == ResourceType.LOAD_BALANCER:
            results.extend(self._evaluate_lb(resource, metric_map))

        return [r for r in results if r.triggered]

    def _evaluate_compute(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        cpu = metrics.get("cpu_utilization")
        net_in = metrics.get("network_in")
        net_out = metrics.get("network_out")
        meta = resource.metadata_ or {}
        itype = resource.instance_type or ""

        # Rule: Idle instance — very low CPU + no network for 14+ days
        if cpu and cpu.avg_value < 5 and cpu.max_value < 10:
            if net_in and net_out and net_in.avg_value < 1000 and net_out.avg_value < 1000:
                results.append(RuleResult(
                    triggered=True,
                    recommendation_type=RecommendationType.TERMINATE,
                    priority=RecommendationPriority.HIGH,
                    title=f"Idle instance: {resource.name or resource.resource_id}",
                    description=(
                        f"Instance has <5% avg CPU and minimal network traffic over "
                        f"{cpu.period_days} days. Consider terminating."
                    ),
                    estimated_savings_pct=1.0,
                ))
            else:
                # Low CPU but some network — rightsize with specific target
                target = _get_downsize_target(itype, cpu.avg_value)
                target_cost = INSTANCE_PRICING.get(target, 0) if target else 0
                current_cost = resource.monthly_cost
                savings_pct = (current_cost - target_cost) / current_cost if target and current_cost > 0 and target_cost > 0 else 0.5

                desc = (
                    f"CPU avg {cpu.avg_value:.1f}% over {cpu.period_days} days. "
                )
                if target:
                    desc += (
                        f"Downsize from {itype} to {target}. "
                        f"Estimated savings: ${current_cost - target_cost:.2f}/mo "
                        f"(${current_cost:.2f} → ${target_cost:.2f})."
                    )
                else:
                    desc += "Consider downsizing to a smaller instance type."

                results.append(RuleResult(
                    triggered=True,
                    recommendation_type=RecommendationType.RIGHTSIZE,
                    priority=RecommendationPriority.HIGH,
                    title=f"Rightsize: {resource.name or resource.resource_id} ({itype})",
                    description=desc,
                    estimated_savings_pct=round(savings_pct, 2) if savings_pct > 0 else 0.5,
                    recommended_config={
                        "current_type": itype,
                        "recommended_type": target,
                    } if target else None,
                ))

        # Rule: Overprovisioned — CPU consistently under 15%
        elif cpu and cpu.avg_value < 15 and cpu.max_value < 40:
            target = _get_downsize_target(itype, cpu.avg_value)
            target_cost = INSTANCE_PRICING.get(target, 0) if target else 0
            current_cost = resource.monthly_cost
            savings_pct = (current_cost - target_cost) / current_cost if target and current_cost > 0 and target_cost > 0 else 0.4

            desc = f"CPU avg {cpu.avg_value:.1f}%, max {cpu.max_value:.1f}% over {cpu.period_days} days. "
            if target:
                desc += (
                    f"Downsize from {itype} to {target}. "
                    f"Estimated savings: ${current_cost - target_cost:.2f}/mo "
                    f"(${current_cost:.2f} → ${target_cost:.2f})."
                )
            else:
                desc += "Downsize recommended."

            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.RIGHTSIZE,
                priority=RecommendationPriority.MEDIUM,
                title=f"Overprovisioned: {resource.name or resource.resource_id} ({itype})",
                description=desc,
                estimated_savings_pct=round(savings_pct, 2) if savings_pct > 0 else 0.4,
                recommended_config={
                    "current_type": itype,
                    "recommended_type": target,
                } if target else None,
            ))

        # Rule: On-demand → Reserved/Savings Plan for steady workloads
        purchase_type = meta.get("purchase_type", "on-demand")
        if purchase_type == "on-demand" and cpu and cpu.avg_value >= 20 and resource.monthly_cost >= 30:
            savings_1yr = resource.monthly_cost * 0.35
            savings_3yr = resource.monthly_cost * 0.60
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.SAVINGS_PLAN,
                priority=RecommendationPriority.MEDIUM,
                title=f"Switch to Reserved/Savings Plan: {resource.name or resource.resource_id}",
                description=(
                    f"This {itype} is running on-demand with steady utilization "
                    f"({cpu.avg_value:.0f}% avg CPU over {cpu.period_days}d). "
                    f"Switch from On-Demand (${resource.monthly_cost:.2f}/mo) to:\n"
                    f"- 1-year Savings Plan: save ~${savings_1yr:.2f}/mo (${savings_1yr * 12:.2f}/yr)\n"
                    f"- 3-year Savings Plan: save ~${savings_3yr:.2f}/mo (${savings_3yr * 12:.2f}/yr)\n"
                    f"Savings Plans apply flexibly across instance families and regions."
                ),
                estimated_savings_pct=0.35,
                recommended_config={
                    "current_pricing": "on-demand",
                    "recommended_pricing": "compute_savings_plan",
                    "current_monthly_cost": round(resource.monthly_cost, 2),
                    "savings_1yr_monthly": round(savings_1yr, 2),
                    "savings_3yr_monthly": round(savings_3yr, 2),
                },
            ))

        # Rule: Spot candidate — non-production, steady low usage
        if resource.tags:
            env = (resource.tags.get("Environment") or resource.tags.get("env") or "").lower()
            if env in ("dev", "development", "staging", "test", "qa"):
                results.append(RuleResult(
                    triggered=True,
                    recommendation_type=RecommendationType.SPOT_CONVERT,
                    priority=RecommendationPriority.LOW,
                    title=f"Spot candidate: {resource.name or resource.resource_id}",
                    description=(
                        f"Non-production ({env}) instance could use spot/preemptible "
                        f"pricing for up to 90% savings."
                    ),
                    estimated_savings_pct=0.7,
                ))

        return results

    def _evaluate_database(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        cpu = metrics.get("cpu_utilization")

        if cpu and cpu.avg_value < 10 and cpu.max_value < 25:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.RIGHTSIZE,
                priority=RecommendationPriority.MEDIUM,
                title=f"Underutilized database: {resource.name or resource.resource_id}",
                description=(
                    f"Database CPU avg {cpu.avg_value:.1f}% over {cpu.period_days} days. "
                    f"Consider downsizing instance class."
                ),
                estimated_savings_pct=0.4,
            ))

        connections = metrics.get("database_connections")
        if connections and connections.max_value < 5:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.TERMINATE,
                priority=RecommendationPriority.HIGH,
                title=f"Possibly idle database: {resource.name or resource.resource_id}",
                description=(
                    f"Max {connections.max_value:.0f} connections over "
                    f"{connections.period_days} days. May be unused."
                ),
                estimated_savings_pct=1.0,
            ))

        return results

    def _evaluate_volume(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        iops = metrics.get("disk_iops")

        # Unattached volume
        is_attached = resource.metadata_ and resource.metadata_.get("attached", True)
        if not is_attached:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.DELETE_VOLUME,
                priority=RecommendationPriority.HIGH,
                title=f"Unattached volume: {resource.name or resource.resource_id}",
                description="Volume is not attached to any instance. Consider deleting.",
                estimated_savings_pct=1.0,
            ))
        elif iops and iops.avg_value < 1:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.DELETE_VOLUME,
                priority=RecommendationPriority.MEDIUM,
                title=f"Zero-IOPS volume: {resource.name or resource.resource_id}",
                description=f"Volume has near-zero IOPS over {iops.period_days} days.",
                estimated_savings_pct=1.0,
            ))

        return results

    def _evaluate_snapshot(self, resource: Resource) -> list[RuleResult]:
        results = []
        age_days = resource.metadata_ and resource.metadata_.get("age_days", 0)
        if age_days and age_days > 90:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.DELETE_SNAPSHOT,
                priority=RecommendationPriority.LOW if age_days < 180 else RecommendationPriority.MEDIUM,
                title=f"Old snapshot ({age_days}d): {resource.name or resource.resource_id}",
                description=f"Snapshot is {age_days} days old. Review retention policy.",
                estimated_savings_pct=1.0,
            ))
        return results

    def _evaluate_ip(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        is_attached = resource.metadata_ and resource.metadata_.get("attached", True)
        if not is_attached:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.RELEASE_IP,
                priority=RecommendationPriority.MEDIUM,
                title=f"Unassociated IP: {resource.resource_id}",
                description="Elastic/Static IP not associated with any resource.",
                estimated_savings_pct=1.0,
            ))
        return results

    def _evaluate_storage(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        access = metrics.get("request_count")
        if access and access.avg_value < 10:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.STORAGE_TIER,
                priority=RecommendationPriority.LOW,
                title=f"Low-access storage: {resource.name or resource.resource_id}",
                description="Very low access rate. Consider moving to cold/archive tier.",
                estimated_savings_pct=0.6,
            ))
        return results

    def _evaluate_lb(self, resource: Resource, metrics: dict) -> list[RuleResult]:
        results = []
        requests = metrics.get("request_count")
        if requests and requests.avg_value < 10:
            results.append(RuleResult(
                triggered=True,
                recommendation_type=RecommendationType.TERMINATE,
                priority=RecommendationPriority.MEDIUM,
                title=f"Low-traffic LB: {resource.name or resource.resource_id}",
                description="Load balancer handling minimal traffic. Consider removing.",
                estimated_savings_pct=1.0,
            ))
        return results
