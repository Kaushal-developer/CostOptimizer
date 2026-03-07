"""AWS Savings Plans and Reserved Instances service."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError

logger = structlog.get_logger(__name__)


class SavingsPlansService:
    """Fetches Savings Plans, RIs, coverage, and utilization from AWS."""

    def __init__(self, credentials: dict[str, str]):
        self._credentials = credentials
        self._log = logger.bind(service="savings_plans")

    def _ce_client(self):
        return boto3.client("ce", region_name="us-east-1", **self._credentials)

    def _sp_client(self):
        return boto3.client("savingsplans", region_name="us-east-1", **self._credentials)

    def _ec2_client(self, region: str = "us-east-1"):
        return boto3.client("ec2", region_name=region, **self._credentials)

    # ------------------------------------------------------------------
    # Savings Plans
    # ------------------------------------------------------------------

    async def get_savings_plans(self) -> list[dict]:
        def _fetch():
            try:
                sp = self._sp_client()
                resp = sp.describe_savings_plans(
                    States=["active", "queued-deleted", "queued"],
                )
                plans = []
                for p in resp.get("SavingsPlans", []):
                    plans.append({
                        "plan_id": p.get("SavingsPlanId"),
                        "plan_type": p.get("SavingsPlanType"),
                        "state": p.get("State"),
                        "commitment_per_hour": float(p.get("Commitment", 0)),
                        "payment_option": p.get("PaymentOption"),
                        "start_time": p.get("Start"),
                        "end_time": p.get("End"),
                        "region": p.get("Region"),
                        "ec2_instance_family": p.get("Ec2InstanceFamily"),
                        "upfront_payment": float(p.get("UpfrontPaymentAmount", 0)),
                        "recurring_payment": float(p.get("RecurringPaymentAmount", 0)),
                    })
                return plans
            except (ClientError, BotoCoreError) as exc:
                self._log.warning("savings_plans_error", error=str(exc))
                return []

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Reserved Instances
    # ------------------------------------------------------------------

    async def get_reserved_instances(self) -> list[dict]:
        def _fetch():
            try:
                ec2 = self._ec2_client()
                resp = ec2.describe_reserved_instances(
                    Filters=[{"Name": "state", "Values": ["active"]}]
                )
                ris = []
                for ri in resp.get("ReservedInstances", []):
                    recurring = sum(
                        float(c.get("Amount", 0)) for c in ri.get("RecurringCharges", [])
                    )
                    ris.append({
                        "ri_id": ri.get("ReservedInstancesId"),
                        "instance_type": ri.get("InstanceType"),
                        "instance_count": ri.get("InstanceCount", 1),
                        "state": ri.get("State"),
                        "offering_type": ri.get("OfferingType"),
                        "fixed_price": float(ri.get("FixedPrice", 0)),
                        "usage_price": float(ri.get("UsagePrice", 0)),
                        "recurring_monthly": round(recurring * 730, 2),
                        "start_time": str(ri.get("Start", "")),
                        "end_time": str(ri.get("End", "")),
                        "scope": ri.get("Scope", "Region"),
                        "product_description": ri.get("ProductDescription", ""),
                        "duration": ri.get("Duration", 0),
                    })
                return ris
            except (ClientError, BotoCoreError) as exc:
                self._log.warning("reserved_instances_error", error=str(exc))
                return []

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Coverage & Utilization
    # ------------------------------------------------------------------

    async def get_coverage(self, days: int = 30) -> dict:
        def _fetch():
            try:
                ce = self._ce_client()
                end = date.today()
                start = end - timedelta(days=days)
                resp = ce.get_savings_plans_coverage(
                    TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                    Granularity="MONTHLY",
                )
                total_coverage = 0.0
                total_on_demand = 0.0
                total_covered = 0.0
                periods = []
                for item in resp.get("SavingsPlansCoverages", []):
                    cov = item.get("Coverage", {})
                    pct = float(cov.get("CoveragePercentage", 0))
                    od = float(cov.get("OnDemandCost", 0))
                    sc = float(cov.get("SpendCoveredBySavingsPlans", 0))
                    total_coverage += pct
                    total_on_demand += od
                    total_covered += sc
                    periods.append({
                        "start": item.get("TimePeriod", {}).get("Start"),
                        "end": item.get("TimePeriod", {}).get("End"),
                        "coverage_pct": round(pct, 1),
                        "on_demand_cost": round(od, 2),
                        "spend_covered": round(sc, 2),
                    })
                n = len(periods) or 1
                return {
                    "avg_coverage_pct": round(total_coverage / n, 1),
                    "total_on_demand": round(total_on_demand, 2),
                    "total_covered": round(total_covered, 2),
                    "periods": periods,
                }
            except (ClientError, BotoCoreError) as exc:
                self._log.warning("coverage_error", error=str(exc))
                return {"avg_coverage_pct": 0, "total_on_demand": 0, "total_covered": 0, "periods": []}

        return await asyncio.to_thread(_fetch)

    async def get_utilization(self, days: int = 30) -> dict:
        def _fetch():
            try:
                ce = self._ce_client()
                end = date.today()
                start = end - timedelta(days=days)
                resp = ce.get_savings_plans_utilization(
                    TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                    Granularity="MONTHLY",
                )
                total = resp.get("Total", {})
                util = total.get("Utilization", {})
                amortized = total.get("AmortizedCommitment", {})
                savings = total.get("Savings", {})
                return {
                    "utilization_pct": round(float(util.get("UtilizationPercentage", 0)), 1),
                    "total_commitment": round(float(amortized.get("TotalAmortizedCommitment", 0)), 2),
                    "used_commitment": round(float(util.get("UsedCommitment", 0)), 2),
                    "unused_commitment": round(float(util.get("UnusedCommitment", 0)), 2),
                    "net_savings": round(float(savings.get("NetSavings", 0)), 2),
                    "on_demand_equivalent": round(float(savings.get("OnDemandCostEquivalent", 0)), 2),
                }
            except (ClientError, BotoCoreError) as exc:
                self._log.warning("utilization_error", error=str(exc))
                return {"utilization_pct": 0, "total_commitment": 0, "used_commitment": 0,
                        "unused_commitment": 0, "net_savings": 0, "on_demand_equivalent": 0}

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Purchase Recommendations
    # ------------------------------------------------------------------

    async def get_purchase_recommendations(self) -> list[dict]:
        def _fetch():
            try:
                ce = self._ce_client()
                resp = ce.get_savings_plans_purchase_recommendation(
                    SavingsPlansType="COMPUTE_SP",
                    TermInYears="ONE_YEAR",
                    PaymentOption="NO_UPFRONT",
                    LookbackPeriodInDays="THIRTY_DAYS",
                )
                recs = []
                for rec in resp.get("SavingsPlansPurchaseRecommendation", {}).get(
                    "SavingsPlansPurchaseRecommendationDetails", []
                ):
                    recs.append({
                        "hourly_commitment": round(float(rec.get("HourlyCommitmentToPurchase", 0)), 4),
                        "estimated_monthly_savings": round(
                            float(rec.get("EstimatedMonthlySavingsAmount", 0)), 2
                        ),
                        "estimated_savings_pct": round(
                            float(rec.get("EstimatedSavingsPercentage", 0)), 1
                        ),
                        "current_on_demand": round(
                            float(rec.get("CurrentAverageHourlyOnDemandSpend", 0)) * 730, 2
                        ),
                        "estimated_on_demand_after": round(
                            float(rec.get("EstimatedAverageUtilization", 0)), 1
                        ),
                        "upfront_cost": round(float(rec.get("UpfrontCost", 0)), 2),
                    })
                return recs
            except (ClientError, BotoCoreError) as exc:
                self._log.warning("purchase_recs_error", error=str(exc))
                return []

        return await asyncio.to_thread(_fetch)
