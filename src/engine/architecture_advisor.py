"""Architecture advisor - current vs optimal architecture with cost projections."""

from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.resource import Resource, ResourceType


class ArchitectureAdvisor:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def analyze(self, tenant_id: int) -> dict:
        """Analyze current architecture and suggest optimizations."""
        # Get resource breakdown
        result = await self._db.execute(
            select(
                Resource.resource_type,
                func.count(),
                func.sum(Resource.monthly_cost),
            )
            .join(Resource.cloud_account)
            .where(Resource.cloud_account.has(tenant_id=tenant_id))
            .group_by(Resource.resource_type)
        )
        rows = result.all()

        current_architecture = {}
        total_cost = 0.0
        for rtype, count, cost in rows:
            cost = cost or 0
            type_val = rtype.value if hasattr(rtype, 'value') else rtype
            current_architecture[type_val] = {
                "count": count,
                "monthly_cost": round(cost, 2),
            }
            total_cost += cost

        # Generate architecture recommendations
        proposals = []

        compute = current_architecture.get("compute", {})
        if compute.get("count", 0) > 5:
            proposals.append({
                "area": "Compute",
                "current": f"{compute['count']} EC2 instances (${compute.get('monthly_cost', 0):,.0f}/mo)",
                "proposed": "Migrate stateless workloads to ECS Fargate or Lambda",
                "savings_pct": 35,
                "savings_amount": round(compute.get("monthly_cost", 0) * 0.35, 2),
                "complexity": "medium",
                "timeline": "4-6 weeks",
            })

        db_resources = current_architecture.get("database", {})
        if db_resources.get("count", 0) > 2:
            proposals.append({
                "area": "Database",
                "current": f"{db_resources['count']} RDS instances (${db_resources.get('monthly_cost', 0):,.0f}/mo)",
                "proposed": "Consolidate to Aurora Serverless v2 with auto-scaling",
                "savings_pct": 40,
                "savings_amount": round(db_resources.get("monthly_cost", 0) * 0.40, 2),
                "complexity": "high",
                "timeline": "6-8 weeks",
            })

        storage = current_architecture.get("storage", {})
        if storage.get("monthly_cost", 0) > 100:
            proposals.append({
                "area": "Storage",
                "current": f"{storage['count']} storage resources (${storage.get('monthly_cost', 0):,.0f}/mo)",
                "proposed": "Implement S3 Intelligent-Tiering and lifecycle policies",
                "savings_pct": 30,
                "savings_amount": round(storage.get("monthly_cost", 0) * 0.30, 2),
                "complexity": "low",
                "timeline": "1-2 weeks",
            })

        if total_cost > 500:
            proposals.append({
                "area": "Networking",
                "current": "Standard inter-region networking",
                "proposed": "Use VPC peering and PrivateLink to reduce data transfer costs",
                "savings_pct": 15,
                "savings_amount": round(total_cost * 0.03, 2),
                "complexity": "medium",
                "timeline": "2-3 weeks",
            })

        if not proposals:
            proposals.append({
                "area": "General",
                "current": "Current architecture",
                "proposed": "Architecture is well-optimized. Consider reserved capacity.",
                "savings_pct": 0,
                "savings_amount": 0,
                "complexity": "low",
                "timeline": "N/A",
            })

        total_potential_savings = sum(p["savings_amount"] for p in proposals)

        return {
            "current_architecture": current_architecture,
            "total_monthly_cost": round(total_cost, 2),
            "proposals": proposals,
            "total_potential_savings": round(total_potential_savings, 2),
            "total_savings_pct": round(total_potential_savings / total_cost * 100, 1) if total_cost > 0 else 0,
        }
