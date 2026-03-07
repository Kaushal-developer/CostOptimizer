"""GCP pricing helper with static lookups and Cloud Billing Catalog API fallback."""

from __future__ import annotations

from typing import Any

from src.core.logging import logger

# ──────────────────────────────────────────────────
# Static pricing tables (on-demand, us-central1, USD/month)
# Updated periodically; used as fast first-pass estimates.
# ──────────────────────────────────────────────────

_MACHINE_TYPE_SPECS: dict[str, dict[str, Any]] = {
    # General-purpose E2
    "e2-micro": {"vcpus": 0.25, "memory_gb": 1, "price_hr": 0.00838},
    "e2-small": {"vcpus": 0.5, "memory_gb": 2, "price_hr": 0.01675},
    "e2-medium": {"vcpus": 1, "memory_gb": 4, "price_hr": 0.03351},
    "e2-standard-2": {"vcpus": 2, "memory_gb": 8, "price_hr": 0.06701},
    "e2-standard-4": {"vcpus": 4, "memory_gb": 16, "price_hr": 0.13402},
    "e2-standard-8": {"vcpus": 8, "memory_gb": 32, "price_hr": 0.26805},
    "e2-standard-16": {"vcpus": 16, "memory_gb": 64, "price_hr": 0.53609},
    "e2-standard-32": {"vcpus": 32, "memory_gb": 128, "price_hr": 1.07218},
    # General-purpose N2
    "n2-standard-2": {"vcpus": 2, "memory_gb": 8, "price_hr": 0.09710},
    "n2-standard-4": {"vcpus": 4, "memory_gb": 16, "price_hr": 0.19420},
    "n2-standard-8": {"vcpus": 8, "memory_gb": 32, "price_hr": 0.38840},
    "n2-standard-16": {"vcpus": 16, "memory_gb": 64, "price_hr": 0.77680},
    "n2-standard-32": {"vcpus": 32, "memory_gb": 128, "price_hr": 1.55360},
    "n2-standard-64": {"vcpus": 64, "memory_gb": 256, "price_hr": 3.10720},
    # N2D
    "n2d-standard-2": {"vcpus": 2, "memory_gb": 8, "price_hr": 0.08450},
    "n2d-standard-4": {"vcpus": 4, "memory_gb": 16, "price_hr": 0.16900},
    "n2d-standard-8": {"vcpus": 8, "memory_gb": 32, "price_hr": 0.33800},
    "n2d-standard-16": {"vcpus": 16, "memory_gb": 64, "price_hr": 0.67600},
    # N1
    "n1-standard-1": {"vcpus": 1, "memory_gb": 3.75, "price_hr": 0.04750},
    "n1-standard-2": {"vcpus": 2, "memory_gb": 7.5, "price_hr": 0.09500},
    "n1-standard-4": {"vcpus": 4, "memory_gb": 15, "price_hr": 0.19000},
    "n1-standard-8": {"vcpus": 8, "memory_gb": 30, "price_hr": 0.38000},
    "n1-standard-16": {"vcpus": 16, "memory_gb": 60, "price_hr": 0.76000},
    # Compute-optimized C2
    "c2-standard-4": {"vcpus": 4, "memory_gb": 16, "price_hr": 0.20990},
    "c2-standard-8": {"vcpus": 8, "memory_gb": 32, "price_hr": 0.41980},
    "c2-standard-16": {"vcpus": 16, "memory_gb": 64, "price_hr": 0.83960},
    "c2-standard-30": {"vcpus": 30, "memory_gb": 120, "price_hr": 1.57430},
    "c2-standard-60": {"vcpus": 60, "memory_gb": 240, "price_hr": 3.14850},
    # Memory-optimized M2
    "m2-ultramem-208": {"vcpus": 208, "memory_gb": 5888, "price_hr": 42.186},
    "m2-ultramem-416": {"vcpus": 416, "memory_gb": 11776, "price_hr": 84.371},
    # GPU A2
    "a2-highgpu-1g": {"vcpus": 12, "memory_gb": 85, "price_hr": 3.67340},
    "a2-highgpu-2g": {"vcpus": 24, "memory_gb": 170, "price_hr": 7.34680},
}

# Disk pricing: USD / GB / month
_DISK_PRICES: dict[str, float] = {
    "pd-standard": 0.040,
    "pd-balanced": 0.100,
    "pd-ssd": 0.170,
    "pd-extreme": 0.125,
    "hyperdisk-balanced": 0.105,
}

# Snapshot pricing: ~$0.026 / GB / month
_SNAPSHOT_PRICE_PER_GB = 0.026

# Static IP (unused): $0.010/hr ~ $7.30/month; in-use is free
_STATIC_IP_UNUSED_MONTHLY = 7.30

# Forwarding rule base cost: ~$0.025/hr ~ $18.25/month
_LB_FORWARDING_RULE_MONTHLY = 18.25

# Cloud SQL tier pricing (approximate monthly, us-central1)
_SQL_TIER_PRICES: dict[str, float] = {
    "db-f1-micro": 7.67,
    "db-g1-small": 25.55,
    "db-n1-standard-1": 51.10,
    "db-n1-standard-2": 102.20,
    "db-n1-standard-4": 204.40,
    "db-n1-standard-8": 408.80,
    "db-n1-standard-16": 817.60,
    "db-n1-standard-32": 1635.20,
    "db-n1-standard-64": 3270.40,
    "db-n1-highmem-2": 130.41,
    "db-n1-highmem-4": 260.82,
    "db-n1-highmem-8": 521.64,
    "db-n1-highmem-16": 1043.28,
}

HOURS_PER_MONTH = 730


class GCPPricingHelper:
    """Provides cost estimates for GCP resources.

    Uses a static lookup table for common machine types with a fallback
    to the Cloud Billing Catalog API for unknown SKUs.
    """

    def __init__(self, project_id: str) -> None:
        self.project_id = project_id
        self._catalog_cache: dict[str, float] = {}
        self._log = logger.bind(component="gcp_pricing")

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def machine_type_specs(self, machine_type: str) -> dict[str, Any]:
        """Return vcpus and memory_gb for a machine type, or empty dict."""
        entry = _MACHINE_TYPE_SPECS.get(machine_type, {})
        if entry:
            vcpus = entry["vcpus"]
            return {
                "vcpus": int(vcpus) if isinstance(vcpus, (int, float)) and vcpus >= 1 else None,
                "memory_gb": entry["memory_gb"],
            }
        # Try to infer from custom machine type name: custom-{vcpus}-{memory_mb}
        if machine_type.startswith("custom-"):
            parts = machine_type.split("-")
            if len(parts) >= 3:
                try:
                    return {
                        "vcpus": int(parts[1]),
                        "memory_gb": round(int(parts[2]) / 1024, 2),
                    }
                except ValueError:
                    pass
        return {}

    def estimate_instance_cost(self, machine_type: str, region: str) -> float:
        """Estimate monthly cost for a Compute Engine instance."""
        entry = _MACHINE_TYPE_SPECS.get(machine_type)
        if entry:
            base = entry["price_hr"] * HOURS_PER_MONTH
            return round(base * _region_multiplier(region), 2)

        # Fallback: try Billing Catalog API
        catalog_price = self._lookup_catalog(
            "Compute Engine", f"N1 Predefined Instance Core running", region
        )
        if catalog_price is not None:
            specs = self.machine_type_specs(machine_type)
            vcpus = specs.get("vcpus") or 1
            return round(catalog_price * vcpus * HOURS_PER_MONTH, 2)

        self._log.warning("price_unknown", machine_type=machine_type, region=region)
        return 0.0

    def estimate_disk_cost(
        self, disk_type: str, size_gb: float, region: str
    ) -> float:
        """Estimate monthly cost for a persistent disk."""
        price = _DISK_PRICES.get(disk_type, _DISK_PRICES["pd-standard"])
        return round(price * size_gb * _region_multiplier(region), 2)

    def estimate_snapshot_cost(self, size_gb: float) -> float:
        """Estimate monthly cost for snapshot storage."""
        return round(_SNAPSHOT_PRICE_PER_GB * size_gb, 2)

    def estimate_static_ip_cost(self, in_use: bool) -> float:
        """Static IPs are free when attached; billed when idle."""
        return 0.0 if in_use else _STATIC_IP_UNUSED_MONTHLY

    def estimate_lb_cost(self, region: str) -> float:
        """Estimate base forwarding-rule cost (excludes data processing)."""
        return round(_LB_FORWARDING_RULE_MONTHLY * _region_multiplier(region), 2)

    def estimate_sql_cost(self, tier: str, region: str) -> float:
        """Estimate monthly Cloud SQL cost by tier."""
        base = _SQL_TIER_PRICES.get(tier)
        if base is not None:
            return round(base * _region_multiplier(region), 2)
        self._log.warning("sql_price_unknown", tier=tier)
        return 0.0

    # ------------------------------------------------------------------
    # Cloud Billing Catalog API fallback
    # ------------------------------------------------------------------

    def _lookup_catalog(
        self, service_display_name: str, sku_description_prefix: str, region: str
    ) -> float | None:
        """Query the Cloud Billing Catalog API for a unit price.

        Returns price per unit per hour, or None if unavailable.
        """
        cache_key = f"{service_display_name}|{sku_description_prefix}|{region}"
        if cache_key in self._catalog_cache:
            return self._catalog_cache[cache_key]

        try:
            from google.cloud import billing_v1

            catalog_client = billing_v1.CloudCatalogClient()
            services = catalog_client.list_services()
            service_name: str | None = None
            for svc in services:
                if svc.display_name == service_display_name:
                    service_name = svc.name
                    break
            if not service_name:
                return None

            skus = catalog_client.list_skus(parent=service_name)
            for sku in skus:
                if not sku.description.startswith(sku_description_prefix):
                    continue
                for region_entry in sku.service_regions:
                    if region in region_entry:
                        for rate in sku.pricing_info:
                            expr = rate.pricing_expression
                            if expr and expr.tiered_rates:
                                nanos = expr.tiered_rates[0].unit_price.nanos
                                units = expr.tiered_rates[0].unit_price.units
                                price = float(units) + float(nanos) / 1e9
                                self._catalog_cache[cache_key] = price
                                return price
        except Exception as exc:
            self._log.debug("catalog_lookup_failed", error=str(exc))

        self._catalog_cache[cache_key] = None  # type: ignore[assignment]
        return None


def _region_multiplier(region: str) -> float:
    """Rough price multiplier relative to us-central1."""
    region = region.lower()
    if region.startswith("us-"):
        return 1.0
    if region.startswith("europe-") or region.startswith("eu-"):
        return 1.10
    if region.startswith("asia-"):
        return 1.15
    if region.startswith("australia-"):
        return 1.20
    if region.startswith("southamerica-"):
        return 1.25
    if region.startswith("northamerica-"):
        return 1.0
    return 1.10  # default non-US
