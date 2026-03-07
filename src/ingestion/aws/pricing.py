"""AWS pricing helper with static lookup tables and Pricing API fallback."""

from __future__ import annotations

from typing import Any

import boto3
import structlog
from botocore.exceptions import ClientError
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

logger = structlog.get_logger(__name__)

# Hours in a month (730 = 365 * 24 / 12)
HOURS_PER_MONTH = 730

# -----------------------------------------------------------------------
# Static on-demand pricing (USD/hr, us-east-1, Linux).
# Kept as a fast path; the Pricing API is used as fallback.
# -----------------------------------------------------------------------
_EC2_ON_DEMAND: dict[str, float] = {
    # General purpose
    "t3.nano": 0.0052, "t3.micro": 0.0104, "t3.small": 0.0208,
    "t3.medium": 0.0416, "t3.large": 0.0832, "t3.xlarge": 0.1664,
    "t3.2xlarge": 0.3328,
    "t3a.nano": 0.0047, "t3a.micro": 0.0094, "t3a.small": 0.0188,
    "t3a.medium": 0.0376, "t3a.large": 0.0752, "t3a.xlarge": 0.1504,
    "t3a.2xlarge": 0.3008,
    "m5.large": 0.096, "m5.xlarge": 0.192, "m5.2xlarge": 0.384,
    "m5.4xlarge": 0.768, "m5.8xlarge": 1.536, "m5.12xlarge": 2.304,
    "m5.16xlarge": 3.072, "m5.24xlarge": 4.608,
    "m6i.large": 0.096, "m6i.xlarge": 0.192, "m6i.2xlarge": 0.384,
    "m6i.4xlarge": 0.768, "m6i.8xlarge": 1.536, "m6i.12xlarge": 2.304,
    "m7i.large": 0.1008, "m7i.xlarge": 0.2016, "m7i.2xlarge": 0.4032,
    # Compute optimized
    "c5.large": 0.085, "c5.xlarge": 0.17, "c5.2xlarge": 0.34,
    "c5.4xlarge": 0.68, "c5.9xlarge": 1.53, "c5.18xlarge": 3.06,
    "c6i.large": 0.085, "c6i.xlarge": 0.17, "c6i.2xlarge": 0.34,
    # Memory optimized
    "r5.large": 0.126, "r5.xlarge": 0.252, "r5.2xlarge": 0.504,
    "r5.4xlarge": 1.008, "r5.8xlarge": 2.016, "r5.12xlarge": 3.024,
    "r6i.large": 0.126, "r6i.xlarge": 0.252, "r6i.2xlarge": 0.504,
    # Graviton
    "m6g.medium": 0.0385, "m6g.large": 0.077, "m6g.xlarge": 0.154,
    "m6g.2xlarge": 0.308, "m6g.4xlarge": 0.616,
    "m7g.medium": 0.0408, "m7g.large": 0.0816, "m7g.xlarge": 0.1632,
    "c6g.large": 0.068, "c6g.xlarge": 0.136, "c6g.2xlarge": 0.272,
    "c7g.large": 0.0725, "c7g.xlarge": 0.145,
    "r6g.large": 0.1008, "r6g.xlarge": 0.2016, "r6g.2xlarge": 0.4032,
}

_RDS_ON_DEMAND: dict[str, float] = {
    "db.t3.micro": 0.017, "db.t3.small": 0.034, "db.t3.medium": 0.068,
    "db.t3.large": 0.136, "db.t3.xlarge": 0.272, "db.t3.2xlarge": 0.544,
    "db.m5.large": 0.171, "db.m5.xlarge": 0.342, "db.m5.2xlarge": 0.684,
    "db.m5.4xlarge": 1.368, "db.m6i.large": 0.171, "db.m6i.xlarge": 0.342,
    "db.r5.large": 0.24, "db.r5.xlarge": 0.48, "db.r5.2xlarge": 0.96,
    "db.r6i.large": 0.24, "db.r6i.xlarge": 0.48,
    "db.r6g.large": 0.192, "db.r6g.xlarge": 0.384,
}

# vcpus, memory_gb for common instance types
_INSTANCE_SPECS: dict[str, dict[str, Any]] = {
    "t3.nano": {"vcpus": 2, "memory_gb": 0.5},
    "t3.micro": {"vcpus": 2, "memory_gb": 1.0},
    "t3.small": {"vcpus": 2, "memory_gb": 2.0},
    "t3.medium": {"vcpus": 2, "memory_gb": 4.0},
    "t3.large": {"vcpus": 2, "memory_gb": 8.0},
    "t3.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "t3.2xlarge": {"vcpus": 8, "memory_gb": 32.0},
    "m5.large": {"vcpus": 2, "memory_gb": 8.0},
    "m5.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "m5.2xlarge": {"vcpus": 8, "memory_gb": 32.0},
    "m5.4xlarge": {"vcpus": 16, "memory_gb": 64.0},
    "m5.8xlarge": {"vcpus": 32, "memory_gb": 128.0},
    "m5.12xlarge": {"vcpus": 48, "memory_gb": 192.0},
    "m6i.large": {"vcpus": 2, "memory_gb": 8.0},
    "m6i.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "m6i.2xlarge": {"vcpus": 8, "memory_gb": 32.0},
    "m7i.large": {"vcpus": 2, "memory_gb": 8.0},
    "m7i.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "c5.large": {"vcpus": 2, "memory_gb": 4.0},
    "c5.xlarge": {"vcpus": 4, "memory_gb": 8.0},
    "c5.2xlarge": {"vcpus": 8, "memory_gb": 16.0},
    "c5.4xlarge": {"vcpus": 16, "memory_gb": 32.0},
    "c6i.large": {"vcpus": 2, "memory_gb": 4.0},
    "c6i.xlarge": {"vcpus": 4, "memory_gb": 8.0},
    "r5.large": {"vcpus": 2, "memory_gb": 16.0},
    "r5.xlarge": {"vcpus": 4, "memory_gb": 32.0},
    "r5.2xlarge": {"vcpus": 8, "memory_gb": 64.0},
    "r5.4xlarge": {"vcpus": 16, "memory_gb": 128.0},
    "r6i.large": {"vcpus": 2, "memory_gb": 16.0},
    "r6i.xlarge": {"vcpus": 4, "memory_gb": 32.0},
    "m6g.large": {"vcpus": 2, "memory_gb": 8.0},
    "m6g.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "m6g.2xlarge": {"vcpus": 8, "memory_gb": 32.0},
    "c6g.large": {"vcpus": 2, "memory_gb": 4.0},
    "c6g.xlarge": {"vcpus": 4, "memory_gb": 8.0},
    "c7g.large": {"vcpus": 2, "memory_gb": 4.0},
    "r6g.large": {"vcpus": 2, "memory_gb": 16.0},
    "r6g.xlarge": {"vcpus": 4, "memory_gb": 32.0},
    # RDS shares similar sizing; prefix stripped when looking up
    "db.t3.micro": {"vcpus": 2, "memory_gb": 1.0},
    "db.t3.small": {"vcpus": 2, "memory_gb": 2.0},
    "db.t3.medium": {"vcpus": 2, "memory_gb": 4.0},
    "db.t3.large": {"vcpus": 2, "memory_gb": 8.0},
    "db.m5.large": {"vcpus": 2, "memory_gb": 8.0},
    "db.m5.xlarge": {"vcpus": 4, "memory_gb": 16.0},
    "db.m5.2xlarge": {"vcpus": 8, "memory_gb": 32.0},
    "db.r5.large": {"vcpus": 2, "memory_gb": 16.0},
    "db.r5.xlarge": {"vcpus": 4, "memory_gb": 32.0},
    "db.r6i.large": {"vcpus": 2, "memory_gb": 16.0},
    "db.r6g.large": {"vcpus": 2, "memory_gb": 16.0},
}

# EBS pricing per GB-month by volume type (us-east-1)
_EBS_GB_MONTH: dict[str, float] = {
    "gp2": 0.10,
    "gp3": 0.08,
    "io1": 0.125,
    "io2": 0.125,
    "st1": 0.045,
    "sc1": 0.015,
    "standard": 0.05,
}

# Provisioned IOPS pricing per IOPS-month
_EBS_IOPS_MONTH: dict[str, float] = {
    "io1": 0.065,
    "io2": 0.065,
}


class AWSPricingHelper:
    """Resolves AWS resource costs via static tables with Pricing API fallback."""

    def __init__(self) -> None:
        self._api_cache: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Instance pricing
    # ------------------------------------------------------------------

    def hourly_rate(self, instance_type: str, region: str = "us-east-1") -> float:
        """Return the on-demand hourly rate for an instance type.

        Checks the static table first, then falls back to the AWS Pricing API.
        Returns 0.0 if the price cannot be determined.
        """
        cache_key = f"{instance_type}:{region}"
        if cache_key in self._api_cache:
            return self._api_cache[cache_key]

        # Static lookup (us-east-1 prices; good enough for estimates)
        rate = _EC2_ON_DEMAND.get(instance_type) or _RDS_ON_DEMAND.get(instance_type)
        if rate is not None:
            return rate

        # Pricing API fallback
        rate = self._fetch_price_from_api(instance_type, region)
        self._api_cache[cache_key] = rate
        return rate

    def monthly_cost(self, instance_type: str, region: str = "us-east-1") -> float:
        """Return estimated monthly on-demand cost."""
        return round(self.hourly_rate(instance_type, region) * HOURS_PER_MONTH, 2)

    def instance_specs(self, instance_type: str) -> dict[str, Any]:
        """Return vcpus and memory_gb for known instance types."""
        return _INSTANCE_SPECS.get(instance_type, {})

    # ------------------------------------------------------------------
    # EBS pricing
    # ------------------------------------------------------------------

    @staticmethod
    def ebs_monthly_cost(volume_type: str, size_gb: int, iops: int = 0) -> float:
        """Calculate monthly cost for an EBS volume."""
        gb_rate = _EBS_GB_MONTH.get(volume_type, 0.10)
        cost = size_gb * gb_rate
        # gp3 includes 3000 IOPS free; io1/io2 charge per provisioned IOPS
        if volume_type in _EBS_IOPS_MONTH and iops > 0:
            cost += iops * _EBS_IOPS_MONTH[volume_type]
        return round(cost, 2)

    # ------------------------------------------------------------------
    # RI / Savings Plan helpers
    # ------------------------------------------------------------------

    @staticmethod
    def ri_coverage(
        reserved_instances: list[dict],
        running_instances: list[dict],
    ) -> dict[str, Any]:
        """Compute basic RI coverage statistics.

        Args:
            reserved_instances: List of RI dicts with 'instance_type' and 'count'.
            running_instances: List of running instance dicts with 'instance_type'.

        Returns:
            Dict with coverage_pct, covered_count, uncovered_count, uncovered_types.
        """
        ri_pool: dict[str, int] = {}
        for ri in reserved_instances:
            itype = ri.get("instance_type", "")
            ri_pool[itype] = ri_pool.get(itype, 0) + ri.get("count", 0)

        covered = 0
        uncovered = 0
        uncovered_types: dict[str, int] = {}
        for inst in running_instances:
            itype = inst.get("instance_type", "")
            if ri_pool.get(itype, 0) > 0:
                ri_pool[itype] -= 1
                covered += 1
            else:
                uncovered += 1
                uncovered_types[itype] = uncovered_types.get(itype, 0) + 1

        total = covered + uncovered
        return {
            "coverage_pct": round((covered / total) * 100, 1) if total else 0.0,
            "covered_count": covered,
            "uncovered_count": uncovered,
            "uncovered_types": uncovered_types,
        }

    @staticmethod
    def savings_plan_effective_rate(
        commitment_hourly: float,
        actual_on_demand_hourly: float,
    ) -> dict[str, float]:
        """Compare Savings Plan commitment against on-demand equivalent.

        Returns savings_pct and monthly_savings.
        """
        if actual_on_demand_hourly <= 0:
            return {"savings_pct": 0.0, "monthly_savings": 0.0}
        savings_pct = round(
            (1 - commitment_hourly / actual_on_demand_hourly) * 100, 1
        )
        monthly_savings = round(
            (actual_on_demand_hourly - commitment_hourly) * HOURS_PER_MONTH, 2
        )
        return {"savings_pct": max(savings_pct, 0.0), "monthly_savings": max(monthly_savings, 0.0)}

    # ------------------------------------------------------------------
    # Pricing API fallback
    # ------------------------------------------------------------------

    @staticmethod
    @retry(
        retry=retry_if_exception_type(ClientError),
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=10),
        reraise=True,
    )
    def _fetch_price_from_api(instance_type: str, region: str) -> float:
        """Query the AWS Pricing API for on-demand Linux pricing.

        The Pricing API is only available in us-east-1 and ap-south-1.
        Returns 0.0 if the price cannot be resolved.
        """
        try:
            import json

            pricing = boto3.client("pricing", region_name="us-east-1")
            filters = [
                {"Type": "TERM_MATCH", "Field": "instanceType", "Value": instance_type},
                {"Type": "TERM_MATCH", "Field": "operatingSystem", "Value": "Linux"},
                {"Type": "TERM_MATCH", "Field": "tenancy", "Value": "Shared"},
                {"Type": "TERM_MATCH", "Field": "preInstalledSw", "Value": "NA"},
                {"Type": "TERM_MATCH", "Field": "capacitystatus", "Value": "Used"},
            ]
            resp = pricing.get_products(
                ServiceCode="AmazonEC2",
                Filters=filters,
                MaxResults=1,
            )
            for price_json in resp.get("PriceList", []):
                data = json.loads(price_json) if isinstance(price_json, str) else price_json
                on_demand = data.get("terms", {}).get("OnDemand", {})
                for term in on_demand.values():
                    for dim in term.get("priceDimensions", {}).values():
                        usd = dim.get("pricePerUnit", {}).get("USD", "0")
                        rate = float(usd)
                        if rate > 0:
                            return rate
        except Exception as exc:
            logger.warning("pricing_api_fallback_failed", instance_type=instance_type, error=str(exc))
        return 0.0
