"""ML-powered cost savings engine using statistical analysis.

Ported from awscostv2 CostSavingsAI patterns, adapted for local DB data.
Uses linear regression, z-scores, HHI index, and temporal pattern detection.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class SavingsOpportunity:
    title: str
    description: str
    category: str  # trend, anomaly, concentration, scheduling, idle, storage, commitment
    priority: str  # critical, high, medium, low
    estimated_monthly_savings: float
    confidence: float  # 0-100
    actions: list[str] = field(default_factory=list)


def _linear_regression(ys: list[float]) -> tuple[float, float]:
    """OLS linear regression. Returns (slope, r_squared)."""
    n = len(ys)
    if n < 3:
        return 0.0, 0.0
    xs = list(range(n))
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    ss_xx = sum((x - x_mean) ** 2 for x in xs)
    ss_yy = sum((y - y_mean) ** 2 for y in ys)
    if ss_xx == 0 or ss_yy == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    r_squared = (ss_xy ** 2) / (ss_xx * ss_yy)
    return slope, r_squared


def _z_scores(values: list[float]) -> list[float]:
    """Compute z-scores for anomaly detection."""
    if len(values) < 3:
        return [0.0] * len(values)
    mean = sum(values) / len(values)
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
    if std == 0:
        return [0.0] * len(values)
    return [(v - mean) / std for v in values]


def _hhi(shares: list[float]) -> float:
    """Herfindahl-Hirschman Index for concentration measurement.
    Returns 0-10000. >2500 = highly concentrated."""
    total = sum(shares)
    if total == 0:
        return 0.0
    return sum((s / total * 100) ** 2 for s in shares)


class MLSavingsEngine:
    """Analyzes cost data to find savings opportunities using statistical methods."""

    def analyze_all(
        self,
        daily_costs: list[dict],  # [{date, service, cost}]
        monthly_costs: list[dict] | None = None,  # [{month, cost}]
        service_costs: dict[str, float] | None = None,  # {service: total_cost}
        region_costs: dict[str, float] | None = None,
        usage_type_costs: dict[str, float] | None = None,
        coverage_pct: float = 0.0,
    ) -> list[SavingsOpportunity]:
        """Run all analysis modules and return combined opportunities."""
        opportunities: list[SavingsOpportunity] = []

        # 1. Cost trend analysis
        try:
            opportunities.extend(self._analyze_cost_trend(daily_costs))
        except Exception as e:
            logger.warning("trend_analysis_failed", error=str(e))

        # 2. Service concentration
        if service_costs:
            try:
                opportunities.extend(self._analyze_service_concentration(service_costs))
            except Exception as e:
                logger.warning("concentration_analysis_failed", error=str(e))

        # 3. Service spike detection
        try:
            opportunities.extend(self._analyze_service_spikes(daily_costs))
        except Exception as e:
            logger.warning("spike_analysis_failed", error=str(e))

        # 4. Scheduling opportunities (weekday/weekend patterns)
        try:
            opportunities.extend(self._analyze_scheduling(daily_costs))
        except Exception as e:
            logger.warning("scheduling_analysis_failed", error=str(e))

        # 5. Idle service detection
        if service_costs:
            try:
                opportunities.extend(self._analyze_idle_services(service_costs, daily_costs))
            except Exception as e:
                logger.warning("idle_analysis_failed", error=str(e))

        # 6. Monthly growth trend
        if monthly_costs:
            try:
                opportunities.extend(self._analyze_monthly_growth(monthly_costs))
            except Exception as e:
                logger.warning("growth_analysis_failed", error=str(e))

        # 7. Region waste
        if region_costs:
            try:
                opportunities.extend(self._analyze_region_waste(region_costs))
            except Exception as e:
                logger.warning("region_analysis_failed", error=str(e))

        # 8. Savings Plan coverage gap
        try:
            opportunities.extend(self._analyze_savings_plan_gap(coverage_pct, service_costs or {}))
        except Exception as e:
            logger.warning("sp_analysis_failed", error=str(e))

        # 9. Data transfer costs
        if usage_type_costs:
            try:
                opportunities.extend(self._analyze_data_transfer(usage_type_costs))
            except Exception as e:
                logger.warning("transfer_analysis_failed", error=str(e))

        # Sort by estimated savings descending
        opportunities.sort(key=lambda o: -o.estimated_monthly_savings)
        return opportunities

    # ------------------------------------------------------------------
    # Individual analysis modules
    # ------------------------------------------------------------------

    def _analyze_cost_trend(self, daily_costs: list[dict]) -> list[SavingsOpportunity]:
        """Detect rising cost trends using linear regression."""
        # Aggregate to daily totals
        daily_totals: dict[str, float] = {}
        for d in daily_costs:
            daily_totals[d["date"]] = daily_totals.get(d["date"], 0) + d.get("cost", 0)

        if len(daily_totals) < 7:
            return []

        values = [daily_totals[k] for k in sorted(daily_totals.keys())]
        slope, r_squared = _linear_regression(values)

        if slope > 0 and r_squared > 0.3:
            projected_30d = slope * 30
            avg_daily = sum(values) / len(values)
            pct_increase = (projected_30d / avg_daily * 100) if avg_daily > 0 else 0

            if pct_increase > 10:
                return [SavingsOpportunity(
                    title="Rising Cost Trend Detected",
                    description=f"Costs are increasing at ${slope:.2f}/day (R²={r_squared:.2f}). "
                                f"Projected 30-day increase: ${projected_30d:.2f} ({pct_increase:.0f}%).",
                    category="trend",
                    priority="high" if pct_increase > 20 else "medium",
                    estimated_monthly_savings=projected_30d * 0.5,  # Assume 50% can be avoided
                    confidence=min(r_squared * 100, 95),
                    actions=[
                        "Review recent resource provisioning changes",
                        "Check for runaway auto-scaling events",
                        "Set up cost anomaly alerts",
                    ],
                )]
        return []

    def _analyze_service_concentration(self, service_costs: dict[str, float]) -> list[SavingsOpportunity]:
        """Detect over-reliance on a single service using HHI."""
        if len(service_costs) < 2:
            return []

        values = list(service_costs.values())
        hhi = _hhi(values)

        if hhi > 2500:
            top_service = max(service_costs, key=service_costs.get)  # type: ignore
            top_pct = service_costs[top_service] / sum(values) * 100
            return [SavingsOpportunity(
                title=f"High Service Concentration: {top_service}",
                description=f"HHI index is {hhi:.0f} (>2500 = highly concentrated). "
                            f"{top_service} accounts for {top_pct:.1f}% of spend.",
                category="concentration",
                priority="medium",
                estimated_monthly_savings=service_costs[top_service] * 0.1,
                confidence=70,
                actions=[
                    f"Review {top_service} usage for optimization opportunities",
                    "Consider architectural alternatives to reduce dependency",
                    "Evaluate reserved capacity or savings plans for this service",
                ],
            )]
        return []

    def _analyze_service_spikes(self, daily_costs: list[dict]) -> list[SavingsOpportunity]:
        """Detect service-level cost spikes using z-scores."""
        # Group by service
        service_daily: dict[str, dict[str, float]] = {}
        for d in daily_costs:
            svc = d.get("service") or d.get("key", "Unknown")
            dt = d["date"]
            service_daily.setdefault(svc, {})[dt] = service_daily.get(svc, {}).get(dt, 0) + d.get("cost", 0)

        opportunities = []
        for svc, daily in service_daily.items():
            if len(daily) < 7:
                continue
            values = [daily[k] for k in sorted(daily.keys())]
            z = _z_scores(values)
            # Check if recent values (last 3 days) have high z-scores
            recent_z = z[-3:] if len(z) >= 3 else z
            max_z = max(recent_z) if recent_z else 0

            if max_z > 2.0:
                avg = sum(values) / len(values)
                excess = values[-1] - avg if values else 0
                if excess > 1.0:  # Only flag if excess > $1/day
                    opportunities.append(SavingsOpportunity(
                        title=f"Cost Spike: {svc}",
                        description=f"Recent spending is {max_z:.1f} standard deviations above average. "
                                    f"Daily excess: ${excess:.2f}.",
                        category="anomaly",
                        priority="high" if max_z > 3.0 else "medium",
                        estimated_monthly_savings=excess * 7,  # 1 week of excess
                        confidence=min(max_z * 30, 90),
                        actions=[
                            f"Investigate recent changes in {svc}",
                            "Check for unintended resource provisioning",
                            "Review auto-scaling configuration",
                        ],
                    ))
        return opportunities

    def _analyze_scheduling(self, daily_costs: list[dict]) -> list[SavingsOpportunity]:
        """Detect workloads running 24/7 that could be scheduled."""
        daily_totals: dict[str, float] = {}
        for d in daily_costs:
            daily_totals[d["date"]] = daily_totals.get(d["date"], 0) + d.get("cost", 0)

        if len(daily_totals) < 14:
            return []

        # Separate weekday vs weekend
        weekday_costs = []
        weekend_costs = []
        for dt_str, cost in daily_totals.items():
            try:
                dt = date.fromisoformat(dt_str)
                if dt.weekday() >= 5:
                    weekend_costs.append(cost)
                else:
                    weekday_costs.append(cost)
            except ValueError:
                continue

        if not weekday_costs or not weekend_costs:
            return []

        weekday_avg = sum(weekday_costs) / len(weekday_costs)
        weekend_avg = sum(weekend_costs) / len(weekend_costs)

        # If weekend spend > 60% of weekday, non-prod is running 24/7
        if weekday_avg > 0 and weekend_avg / weekday_avg > 0.6:
            potential_savings = weekend_avg * 8  # ~8 weekend days per month * reduction
            cv = (max(weekday_costs) - min(weekday_costs)) / weekday_avg if weekday_avg > 0 else 1

            if cv < 0.15:  # Very flat spend = always-on pattern
                return [SavingsOpportunity(
                    title="Scheduling Opportunity Detected",
                    description=f"Weekend spend (${weekend_avg:.2f}/day) is {weekend_avg/weekday_avg*100:.0f}% "
                                f"of weekday (${weekday_avg:.2f}/day). Resources may be running unnecessarily 24/7.",
                    category="scheduling",
                    priority="medium",
                    estimated_monthly_savings=potential_savings * 0.4,
                    confidence=65,
                    actions=[
                        "Identify dev/test/staging environments running on weekends",
                        "Implement scheduled start/stop using AWS Instance Scheduler",
                        "Consider spot instances for non-production workloads",
                    ],
                )]
        return []

    def _analyze_idle_services(
        self, service_costs: dict[str, float], daily_costs: list[dict]
    ) -> list[SavingsOpportunity]:
        """Detect services with persistent low, flat spend (likely forgotten)."""
        # Group daily costs by service
        svc_daily: dict[str, list[float]] = {}
        for d in daily_costs:
            svc = d.get("service") or d.get("key", "")
            svc_daily.setdefault(svc, []).append(d.get("cost", 0))

        opportunities = []
        for svc, total in service_costs.items():
            daily_vals = svc_daily.get(svc, [])
            if not daily_vals or len(daily_vals) < 7:
                continue

            avg = sum(daily_vals) / len(daily_vals)
            if avg < 0.5 or avg > 50:
                continue  # Only flag $0.50-$50/day services

            std = math.sqrt(sum((v - avg) ** 2 for v in daily_vals) / len(daily_vals))
            cv = std / avg if avg > 0 else 1

            if cv < 0.5:  # Low variation = idle pattern
                opportunities.append(SavingsOpportunity(
                    title=f"Potentially Idle Service: {svc}",
                    description=f"Spending ${avg:.2f}/day with very low variation (CV={cv:.2f}). "
                                "May be forgotten or underutilized.",
                    category="idle",
                    priority="low",
                    estimated_monthly_savings=avg * 30 * 0.6,
                    confidence=55,
                    actions=[
                        f"Review if {svc} is still needed",
                        "Check for unused resources in this service",
                        "Consider terminating or consolidating",
                    ],
                ))
        return opportunities

    def _analyze_monthly_growth(self, monthly_costs: list[dict]) -> list[SavingsOpportunity]:
        """Detect sustained monthly cost growth."""
        if len(monthly_costs) < 3:
            return []

        values = [m["cost"] for m in sorted(monthly_costs, key=lambda x: x["month"])]
        slope, r_squared = _linear_regression(values)

        if slope > 0 and r_squared > 0.5:
            avg = sum(values) / len(values)
            growth_pct = (slope / avg * 100) if avg > 0 else 0
            if growth_pct > 5:
                return [SavingsOpportunity(
                    title="Sustained Monthly Cost Growth",
                    description=f"Costs growing at ${slope:.2f}/month ({growth_pct:.1f}% MoM). "
                                f"R²={r_squared:.2f} indicates strong trend.",
                    category="trend",
                    priority="high" if growth_pct > 15 else "medium",
                    estimated_monthly_savings=slope * 3,
                    confidence=min(r_squared * 100, 90),
                    actions=[
                        "Review resource provisioning patterns",
                        "Implement cost governance policies",
                        "Set up budget alerts",
                    ],
                )]
        return []

    def _analyze_region_waste(self, region_costs: dict[str, float]) -> list[SavingsOpportunity]:
        """Detect secondary regions with minimal spend (potentially forgotten resources)."""
        if len(region_costs) < 2:
            return []

        total = sum(region_costs.values())
        opportunities = []
        for region, cost in region_costs.items():
            pct = (cost / total * 100) if total > 0 else 0
            if 0 < pct < 5 and cost > 5:  # Small spend in minor regions
                opportunities.append(SavingsOpportunity(
                    title=f"Low Spend in {region}",
                    description=f"Only ${cost:.2f}/mo ({pct:.1f}%) in {region}. "
                                "May contain forgotten resources.",
                    category="idle",
                    priority="low",
                    estimated_monthly_savings=cost * 0.5,
                    confidence=40,
                    actions=[
                        f"Review resources in {region}",
                        "Consolidate to primary regions if possible",
                        "Delete any unused resources",
                    ],
                ))
        return opportunities

    def _analyze_savings_plan_gap(
        self, coverage_pct: float, service_costs: dict[str, float]
    ) -> list[SavingsOpportunity]:
        """Detect low Savings Plan coverage."""
        if coverage_pct >= 60:
            return []

        total = sum(service_costs.values())
        uncovered = total * (1 - coverage_pct / 100)
        potential = uncovered * 0.25  # ~25% savings from SP

        if potential > 10:
            return [SavingsOpportunity(
                title="Low Savings Plan Coverage",
                description=f"Only {coverage_pct:.0f}% of eligible spend is covered by Savings Plans. "
                            f"${uncovered:.2f}/mo is on-demand pricing.",
                category="commitment",
                priority="high" if coverage_pct < 30 else "medium",
                estimated_monthly_savings=potential,
                confidence=80,
                actions=[
                    "Purchase Compute Savings Plans (most flexible)",
                    "Start with 1-year No Upfront for lower risk",
                    "Cover 60-80% of baseline steady-state usage",
                    "Keep remaining on-demand for variable workloads",
                ],
            )]
        return []

    def _analyze_data_transfer(self, usage_type_costs: dict[str, float]) -> list[SavingsOpportunity]:
        """Detect high data transfer costs."""
        transfer_cost = sum(
            cost for ut, cost in usage_type_costs.items()
            if "DataTransfer" in ut or "Bytes" in ut
        )
        total = sum(usage_type_costs.values())

        if transfer_cost > 50 and total > 0 and transfer_cost / total > 0.1:
            return [SavingsOpportunity(
                title="High Data Transfer Costs",
                description=f"Data transfer costs are ${transfer_cost:.2f}/mo "
                            f"({transfer_cost/total*100:.1f}% of total).",
                category="storage",
                priority="medium",
                estimated_monthly_savings=transfer_cost * 0.3,
                confidence=60,
                actions=[
                    "Use VPC endpoints to avoid NAT Gateway charges",
                    "Enable S3 Transfer Acceleration only when needed",
                    "Consider CloudFront for frequently accessed content",
                    "Review cross-region data transfer patterns",
                ],
            )]
        return []

    # ------------------------------------------------------------------
    # Commitment Strategy Recommendation
    # ------------------------------------------------------------------

    def recommend_commitment_strategy(
        self, daily_costs: list[dict], current_coverage_pct: float = 0.0
    ) -> dict[str, Any]:
        """Analyze usage patterns to recommend SP/RI purchase strategy."""
        daily_totals: dict[str, float] = {}
        for d in daily_costs:
            daily_totals[d["date"]] = daily_totals.get(d["date"], 0) + d.get("cost", 0)

        if len(daily_totals) < 14:
            return {"recommendation": "Insufficient data", "details": {}}

        values = sorted(daily_totals.values())
        avg = sum(values) / len(values)
        p10 = values[int(len(values) * 0.1)]  # 10th percentile = baseline
        p50 = values[int(len(values) * 0.5)]  # median

        # Recommend covering baseline (p10) with 3yr, median with 1yr, rest on-demand
        baseline_monthly = p10 * 30
        median_monthly = p50 * 30
        total_monthly = avg * 30

        sp_3yr_savings = baseline_monthly * 0.40  # ~40% discount for 3yr
        sp_1yr_savings = (median_monthly - baseline_monthly) * 0.25  # ~25% for 1yr

        return {
            "recommendation": "Mixed commitment strategy",
            "total_monthly_spend": round(total_monthly, 2),
            "baseline_spend": round(baseline_monthly, 2),
            "median_spend": round(median_monthly, 2),
            "strategy": {
                "3yr_all_upfront": {
                    "coverage": f"${baseline_monthly:.2f}/mo (baseline)",
                    "savings": round(sp_3yr_savings, 2),
                    "description": "Cover steady-state baseline with 3-year All Upfront SP",
                },
                "1yr_no_upfront": {
                    "coverage": f"${median_monthly - baseline_monthly:.2f}/mo (variable baseline)",
                    "savings": round(sp_1yr_savings, 2),
                    "description": "Cover variable baseline with 1-year No Upfront SP",
                },
                "on_demand": {
                    "coverage": f"${total_monthly - median_monthly:.2f}/mo (peaks)",
                    "description": "Keep burst/peak usage on-demand for flexibility",
                },
            },
            "total_estimated_savings": round(sp_3yr_savings + sp_1yr_savings, 2),
            "current_coverage": current_coverage_pct,
        }
