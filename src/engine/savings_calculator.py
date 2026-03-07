"""
Savings calculator — aggregates recommendations into financial summaries.
"""

from dataclasses import dataclass, field
from src.models.recommendation import Recommendation, RecommendationType, RecommendationPriority


@dataclass
class SavingsByCategory:
    category: str
    current_cost: float = 0.0
    estimated_cost: float = 0.0
    potential_savings: float = 0.0
    recommendation_count: int = 0


@dataclass
class SavingsSummary:
    total_monthly_spend: float = 0.0
    total_potential_savings: float = 0.0
    savings_percentage: float = 0.0
    optimization_score: float = 0.0
    by_type: dict[str, SavingsByCategory] = field(default_factory=dict)
    by_priority: dict[str, float] = field(default_factory=dict)
    top_recommendations: list[dict] = field(default_factory=list)


class SavingsCalculator:
    """Calculate total savings potential from recommendations."""

    def calculate(
        self,
        recommendations: list[Recommendation],
        total_monthly_spend: float,
    ) -> SavingsSummary:
        summary = SavingsSummary(total_monthly_spend=total_monthly_spend)

        for rec in recommendations:
            savings = rec.estimated_savings

            # By type
            rtype = rec.type.value
            if rtype not in summary.by_type:
                summary.by_type[rtype] = SavingsByCategory(category=rtype)
            cat = summary.by_type[rtype]
            cat.current_cost += rec.current_monthly_cost
            cat.estimated_cost += rec.estimated_monthly_cost
            cat.potential_savings += savings
            cat.recommendation_count += 1

            # By priority
            prio = rec.priority.value
            summary.by_priority[prio] = summary.by_priority.get(prio, 0) + savings

            summary.total_potential_savings += savings

        # Calculate percentages
        if total_monthly_spend > 0:
            summary.savings_percentage = round(
                (summary.total_potential_savings / total_monthly_spend) * 100, 1
            )

        # Optimization score: 100 = no waste, 0 = all waste
        summary.optimization_score = round(max(0, 100 - summary.savings_percentage), 1)

        # Top recommendations sorted by savings
        sorted_recs = sorted(recommendations, key=lambda r: r.estimated_savings, reverse=True)
        summary.top_recommendations = [
            {
                "id": r.id,
                "title": r.title,
                "type": r.type.value,
                "priority": r.priority.value,
                "estimated_savings": r.estimated_savings,
                "resource_id": r.resource_id,
            }
            for r in sorted_recs[:20]
        ]

        return summary

    def calculate_what_if(
        self,
        recommendations: list[Recommendation],
        total_monthly_spend: float,
        apply_types: list[RecommendationType] | None = None,
        apply_priorities: list[RecommendationPriority] | None = None,
    ) -> SavingsSummary:
        """What-if analysis: calculate savings if only certain types/priorities are applied."""
        filtered = recommendations
        if apply_types:
            filtered = [r for r in filtered if r.type in apply_types]
        if apply_priorities:
            filtered = [r for r in filtered if r.priority in apply_priorities]
        return self.calculate(filtered, total_monthly_spend)
