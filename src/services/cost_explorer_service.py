"""AWS Cost Explorer service for fetching and caching cost data."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cost_data import DailyCost, CostAnomaly, CostForecast, MonthlyBill

logger = structlog.get_logger(__name__)


class CostExplorerService:
    """Fetches cost data from AWS Cost Explorer and caches in DB."""

    def __init__(self, credentials: dict[str, str]):
        self._credentials = credentials
        self._log = logger.bind(service="cost_explorer")

    def _ce_client(self):
        return boto3.client("ce", region_name="us-east-1", **self._credentials)

    # ------------------------------------------------------------------
    # Daily costs
    # ------------------------------------------------------------------

    async def get_daily_costs(
        self, days: int = 30, group_by: str = "SERVICE"
    ) -> list[dict]:
        end = date.today()
        start = end - timedelta(days=days)

        def _fetch():
            ce = self._ce_client()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="DAILY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": group_by}],
            )
            results = []
            for period in resp.get("ResultsByTime", []):
                period_date = period["TimePeriod"]["Start"]
                for group in period.get("Groups", []):
                    results.append({
                        "date": period_date,
                        "key": group["Keys"][0],
                        "cost": float(group["Metrics"]["UnblendedCost"]["Amount"]),
                    })
                # Also capture ungrouped total
                if not period.get("Groups"):
                    total = float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                    results.append({"date": period_date, "key": "Total", "cost": total})
            return results

        return await asyncio.to_thread(_fetch)

    async def get_cost_by_service(self, days: int = 30) -> dict[str, float]:
        end = date.today()
        start = end - timedelta(days=days)

        def _fetch():
            ce = self._ce_client()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            by_service: dict[str, float] = {}
            for period in resp.get("ResultsByTime", []):
                for group in period.get("Groups", []):
                    svc = group["Keys"][0]
                    amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    by_service[svc] = by_service.get(svc, 0.0) + amt
            return {k: round(v, 2) for k, v in sorted(by_service.items(), key=lambda x: -x[1])}

        return await asyncio.to_thread(_fetch)

    async def get_cost_by_region(self, days: int = 30) -> dict[str, float]:
        end = date.today()
        start = end - timedelta(days=days)

        def _fetch():
            ce = self._ce_client()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "REGION"}],
            )
            by_region: dict[str, float] = {}
            for period in resp.get("ResultsByTime", []):
                for group in period.get("Groups", []):
                    rgn = group["Keys"][0]
                    amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    by_region[rgn] = by_region.get(rgn, 0.0) + amt
            return {k: round(v, 2) for k, v in sorted(by_region.items(), key=lambda x: -x[1])}

        return await asyncio.to_thread(_fetch)

    async def get_cost_by_usage_type(self, days: int = 30, top_n: int = 20) -> dict[str, float]:
        end = date.today()
        start = end - timedelta(days=days)

        def _fetch():
            ce = self._ce_client()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
                GroupBy=[{"Type": "DIMENSION", "Key": "USAGE_TYPE"}],
            )
            by_usage: dict[str, float] = {}
            for period in resp.get("ResultsByTime", []):
                for group in period.get("Groups", []):
                    key = group["Keys"][0]
                    amt = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    by_usage[key] = by_usage.get(key, 0.0) + amt
            sorted_items = sorted(by_usage.items(), key=lambda x: -x[1])[:top_n]
            return {k: round(v, 2) for k, v in sorted_items}

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Monthly trend
    # ------------------------------------------------------------------

    async def get_monthly_trend(self, months: int = 12) -> list[dict]:
        end = date.today().replace(day=1)
        start = (end - timedelta(days=months * 31)).replace(day=1)

        def _fetch():
            ce = self._ce_client()
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            results = []
            for period in resp.get("ResultsByTime", []):
                results.append({
                    "month": period["TimePeriod"]["Start"],
                    "cost": round(float(period.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0)), 2),
                })
            return results

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Cost summary
    # ------------------------------------------------------------------

    async def get_cost_summary(self, days: int = 30) -> dict:
        end = date.today()
        start = end - timedelta(days=days)
        prev_start = start - timedelta(days=days)

        def _fetch():
            ce = self._ce_client()
            # Current period
            current = ce.get_cost_and_usage(
                TimePeriod={"Start": start.isoformat(), "End": end.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            current_total = sum(
                float(p.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                for p in current.get("ResultsByTime", [])
            )
            # Previous period for comparison
            previous = ce.get_cost_and_usage(
                TimePeriod={"Start": prev_start.isoformat(), "End": start.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost"],
            )
            prev_total = sum(
                float(p.get("Total", {}).get("UnblendedCost", {}).get("Amount", 0))
                for p in previous.get("ResultsByTime", [])
            )
            change_pct = ((current_total - prev_total) / prev_total * 100) if prev_total > 0 else 0.0
            return {
                "current_period_cost": round(current_total, 2),
                "previous_period_cost": round(prev_total, 2),
                "change_percentage": round(change_pct, 1),
                "period_days": days,
            }

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Anomalies
    # ------------------------------------------------------------------

    async def get_cost_anomalies(self) -> list[dict]:
        def _fetch():
            ce = self._ce_client()
            end_str = date.today().isoformat() + "T23:59:59Z"
            start_str = (date.today() - timedelta(days=90)).isoformat() + "T00:00:00Z"
            try:
                resp = ce.get_anomalies(
                    DateInterval={"StartDate": start_str, "EndDate": end_str},
                    MaxResults=20,
                )
                anomalies = []
                for a in resp.get("Anomalies", []):
                    impact = a.get("Impact", {})
                    anomalies.append({
                        "anomaly_id": a.get("AnomalyId"),
                        "start_date": a.get("AnomalyStartDate"),
                        "end_date": a.get("AnomalyEndDate"),
                        "expected_spend": float(impact.get("MaxImpact", 0)),
                        "actual_spend": float(impact.get("TotalActualSpend", 0)),
                        "total_impact": float(impact.get("TotalImpact", 0)),
                        "root_causes": a.get("RootCauses", []),
                    })
                return anomalies
            except (ClientError, BotoCoreError) as exc:
                logger.warning("anomalies_not_available", error=str(exc))
                return []

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Forecast
    # ------------------------------------------------------------------

    async def get_cost_forecast(self, months: int = 3) -> dict:
        def _fetch():
            ce = self._ce_client()
            start = (date.today() + timedelta(days=1)).isoformat()
            end = (date.today() + timedelta(days=months * 30)).isoformat()
            try:
                resp = ce.get_cost_forecast(
                    TimePeriod={"Start": start, "End": end},
                    Metric="UNBLENDED_COST",
                    Granularity="MONTHLY",
                )
                total = resp.get("Total", {})
                forecasts = []
                for item in resp.get("ForecastResultsByTime", []):
                    forecasts.append({
                        "period_start": item["TimePeriod"]["Start"],
                        "period_end": item["TimePeriod"]["End"],
                        "mean": round(float(item.get("MeanValue", 0)), 2),
                        "lower": round(float(item.get("PredictionIntervalLowerBound", 0)), 2),
                        "upper": round(float(item.get("PredictionIntervalUpperBound", 0)), 2),
                    })
                return {
                    "total_forecasted": round(float(total.get("Amount", 0)), 2),
                    "periods": forecasts,
                }
            except (ClientError, BotoCoreError) as exc:
                logger.warning("forecast_not_available", error=str(exc))
                return {"total_forecasted": 0, "periods": []}

        return await asyncio.to_thread(_fetch)

    # ------------------------------------------------------------------
    # Cache to DB
    # ------------------------------------------------------------------

    async def cache_daily_costs(self, db: AsyncSession, account_id: int, days: int = 90) -> int:
        """Fetch daily costs and cache in DB. Returns count of rows stored."""
        daily = await self.get_daily_costs(days=days, group_by="SERVICE")

        # Clear old data for this account within the period
        cutoff = date.today() - timedelta(days=days)
        await db.execute(
            delete(DailyCost).where(
                DailyCost.cloud_account_id == account_id,
                DailyCost.cost_date >= cutoff,
            )
        )

        count = 0
        for entry in daily:
            cost_date = datetime.strptime(entry["date"], "%Y-%m-%d").date()
            db.add(DailyCost(
                cloud_account_id=account_id,
                cost_date=cost_date,
                service=entry["key"],
                cost=round(entry["cost"], 4),
            ))
            count += 1

        await db.flush()
        return count

    async def cache_monthly_bills(self, db: AsyncSession, account_id: int, months: int = 12) -> int:
        """Fetch monthly cost breakdown and store as bills."""
        trend = await self.get_monthly_trend(months=months)
        by_service = await self.get_cost_by_service(days=months * 31)
        by_region = await self.get_cost_by_region(days=months * 31)

        count = 0
        for entry in trend:
            bill_month = datetime.strptime(entry["month"], "%Y-%m-%d").date()
            db.add(MonthlyBill(
                cloud_account_id=account_id,
                bill_month=bill_month,
                total=entry["cost"],
                by_service=by_service,
                by_region=by_region,
            ))
            count += 1

        await db.flush()
        return count
