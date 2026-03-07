"""Azure pricing helper: static lookup with REST API fallback."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from src.core.logging import logger

# ---------------------------------------------------------------------------
# Static pricing table (on-demand, pay-as-you-go, USD/hour)
# Region key: "eastus" style; values are representative list prices.
# ---------------------------------------------------------------------------

_VM_HOURLY_PRICES: dict[str, dict[str, float]] = {
    "Standard_B1s": {"eastus": 0.0104, "westus2": 0.0104, "westeurope": 0.0118},
    "Standard_B2s": {"eastus": 0.0416, "westus2": 0.0416, "westeurope": 0.0472},
    "Standard_B2ms": {"eastus": 0.0832, "westus2": 0.0832, "westeurope": 0.0946},
    "Standard_D2s_v5": {"eastus": 0.096, "westus2": 0.096, "westeurope": 0.109},
    "Standard_D4s_v5": {"eastus": 0.192, "westus2": 0.192, "westeurope": 0.218},
    "Standard_D8s_v5": {"eastus": 0.384, "westus2": 0.384, "westeurope": 0.436},
    "Standard_D16s_v5": {"eastus": 0.768, "westus2": 0.768, "westeurope": 0.872},
    "Standard_D32s_v5": {"eastus": 1.536, "westus2": 1.536, "westeurope": 1.744},
    "Standard_E2s_v5": {"eastus": 0.126, "westus2": 0.126, "westeurope": 0.143},
    "Standard_E4s_v5": {"eastus": 0.252, "westus2": 0.252, "westeurope": 0.286},
    "Standard_E8s_v5": {"eastus": 0.504, "westus2": 0.504, "westeurope": 0.572},
    "Standard_F2s_v2": {"eastus": 0.0846, "westus2": 0.0846, "westeurope": 0.096},
    "Standard_F4s_v2": {"eastus": 0.169, "westus2": 0.169, "westeurope": 0.192},
    "Standard_F8s_v2": {"eastus": 0.338, "westus2": 0.338, "westeurope": 0.384},
}

_MANAGED_DISK_MONTHLY: dict[str, float] = {
    "Standard_LRS": 0.04,   # per GB/month
    "StandardSSD_LRS": 0.075,
    "Premium_LRS": 0.12,
    "UltraSSD_LRS": 0.18,
}

HOURS_PER_MONTH = 730


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def estimate_vm_monthly_cost(vm_size: str, region: str) -> float | None:
    """Return estimated monthly cost from the static table, or None."""
    size_entry = _VM_HOURLY_PRICES.get(vm_size)
    if size_entry is None:
        return None
    hourly = size_entry.get(region) or size_entry.get("eastus")
    if hourly is None:
        return None
    return round(hourly * HOURS_PER_MONTH, 2)


def estimate_disk_monthly_cost(sku_name: str, size_gb: float) -> float:
    """Return estimated monthly cost for a managed disk."""
    per_gb = _MANAGED_DISK_MONTHLY.get(sku_name, 0.04)
    return round(per_gb * size_gb, 2)


# ---------------------------------------------------------------------------
# Azure Retail Prices API fallback
# https://learn.microsoft.com/en-us/rest/api/cost-management/retail-prices
# ---------------------------------------------------------------------------

_RETAIL_API = "https://prices.azure.com/api/retail/prices"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def fetch_vm_price(vm_size: str, region: str) -> float | None:
    """Query Azure Retail Prices API for on-demand Linux VM pricing.

    Returns monthly cost or None if not found.
    """
    arm_region = _normalize_region(region)
    odata_filter = (
        f"serviceName eq 'Virtual Machines' "
        f"and armSkuName eq '{vm_size}' "
        f"and armRegionName eq '{arm_region}' "
        f"and priceType eq 'Consumption' "
        f"and contains(meterName, 'Spot') eq false "
        f"and contains(meterName, 'Low Priority') eq false"
    )
    params: dict[str, Any] = {"$filter": odata_filter, "currencyCode": "USD"}

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(_RETAIL_API, params=params)
            resp.raise_for_status()
            data = resp.json()

        items: list[dict] = data.get("Items", [])
        # Prefer Linux pay-as-you-go
        for item in items:
            product_name: str = item.get("productName", "")
            if "Windows" in product_name:
                continue
            unit_price: float = item.get("retailPrice", 0.0)
            unit_of_measure: str = item.get("unitOfMeasure", "")
            if "Hour" in unit_of_measure and unit_price > 0:
                monthly = round(unit_price * HOURS_PER_MONTH, 2)
                logger.debug(
                    "azure_pricing_api_hit",
                    vm_size=vm_size,
                    region=arm_region,
                    monthly_cost=monthly,
                )
                return monthly

        logger.warning("azure_pricing_api_no_match", vm_size=vm_size, region=arm_region)
        return None

    except Exception:
        logger.warning("azure_pricing_api_error", vm_size=vm_size, region=arm_region, exc_info=True)
        return None


async def get_vm_monthly_cost(vm_size: str, region: str) -> float:
    """Static lookup first, then API fallback, then 0.0."""
    cost = estimate_vm_monthly_cost(vm_size, region)
    if cost is not None:
        return cost
    api_cost = await fetch_vm_price(vm_size, region)
    return api_cost if api_cost is not None else 0.0


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _normalize_region(region: str) -> str:
    """Ensure the region string matches ARM naming (lowercase, no spaces)."""
    return region.lower().replace(" ", "")
