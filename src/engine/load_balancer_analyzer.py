"""Load balancing analyzer - AZ/region distribution, rebalancing, auto-scaling recommendations."""

from __future__ import annotations

import random
from collections import defaultdict
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.resource import Resource, ResourceType


class LoadBalancerAnalyzer:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def analyze_distribution(self, tenant_id: int) -> dict:
        """Analyze resource distribution across regions and AZs."""
        result = await self._db.execute(
            select(Resource.region, Resource.resource_type, func.count(), func.sum(Resource.monthly_cost))
            .join(Resource.cloud_account)
            .where(Resource.cloud_account.has(tenant_id=tenant_id))
            .group_by(Resource.region, Resource.resource_type)
        )
        rows = result.all()

        by_region: dict[str, dict] = defaultdict(lambda: {"count": 0, "cost": 0, "types": {}})
        total_resources = 0
        total_cost = 0.0

        for region, rtype, count, cost in rows:
            cost = cost or 0
            by_region[region]["count"] += count
            by_region[region]["cost"] += cost
            by_region[region]["types"][rtype.value if hasattr(rtype, 'value') else rtype] = count
            total_resources += count
            total_cost += cost

        # Calculate distribution percentages
        distribution = {}
        for region, data in by_region.items():
            distribution[region] = {
                "count": data["count"],
                "cost": round(data["cost"], 2),
                "count_pct": round(data["count"] / total_resources * 100, 1) if total_resources > 0 else 0,
                "cost_pct": round(data["cost"] / total_cost * 100, 1) if total_cost > 0 else 0,
                "types": data["types"],
            }

        # Calculate imbalance score (0=balanced, 1=highly imbalanced)
        if len(distribution) > 1:
            pcts = [d["count_pct"] for d in distribution.values()]
            ideal = 100 / len(pcts)
            imbalance = sum(abs(p - ideal) for p in pcts) / (2 * 100)
        else:
            imbalance = 0

        recommendations = self._generate_recommendations(distribution, imbalance, total_cost)

        return {
            "total_resources": total_resources,
            "total_monthly_cost": round(total_cost, 2),
            "regions": len(distribution),
            "distribution": distribution,
            "imbalance_score": round(imbalance, 3),
            "recommendations": recommendations,
        }

    def _generate_recommendations(self, distribution: dict, imbalance: float, total_cost: float) -> list[dict]:
        recs = []
        if imbalance > 0.3:
            recs.append({
                "type": "rebalance",
                "title": "Rebalance resources across regions",
                "description": f"Resource distribution imbalance of {imbalance:.0%}. Consider redistributing workloads.",
                "estimated_savings": round(total_cost * 0.05, 2),
                "priority": "high",
            })

        if len(distribution) == 1:
            recs.append({
                "type": "multi_region",
                "title": "Add multi-region deployment",
                "description": "All resources are in a single region. Consider multi-region for resilience and latency.",
                "estimated_savings": 0,
                "priority": "medium",
            })

        for region, data in distribution.items():
            if data["cost_pct"] > 60:
                recs.append({
                    "type": "cost_concentration",
                    "title": f"High cost concentration in {region}",
                    "description": f"{data['cost_pct']}% of costs are in {region}. Review for spot/reserved opportunities.",
                    "estimated_savings": round(data["cost"] * 0.15, 2),
                    "priority": "medium",
                })

        if not recs:
            recs.append({
                "type": "balanced",
                "title": "Distribution looks healthy",
                "description": "Resources are well-distributed across regions.",
                "estimated_savings": 0,
                "priority": "low",
            })

        return recs
