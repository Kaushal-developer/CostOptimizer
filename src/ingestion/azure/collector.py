"""Azure cloud resource collector."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient
from azure.mgmt.sql import SqlManagementClient
from azure.mgmt.storage import StorageManagementClient
from azure.mgmt.containerservice import ContainerServiceClient
from azure.mgmt.costmanagement import CostManagementClient
from azure.mgmt.monitor import MonitorManagementClient
from azure.mgmt.resource import ResourceManagementClient
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.core.logging import logger
from src.ingestion.base import BaseCollector, CollectedMetric, CollectedResource
from src.ingestion.azure.pricing import (
    estimate_disk_monthly_cost,
    get_vm_monthly_cost,
)
from src.models.resource import ResourceType


# ---------------------------------------------------------------------------
# Retry decorator for transient Azure errors
# ---------------------------------------------------------------------------

_azure_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=2, max=30),
    retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    reraise=True,
)


# ---------------------------------------------------------------------------
# Helpers to run sync SDK paginators in a thread
# ---------------------------------------------------------------------------

async def _run_sync(func: Any, *args: Any, **kwargs: Any) -> Any:
    """Execute a synchronous Azure SDK call in a background thread."""
    return await asyncio.to_thread(func, *args, **kwargs)


def _list_all(pageable: Any) -> list[Any]:
    """Drain a sync Azure pageable into a plain list (runs on caller thread)."""
    return list(pageable)


def _tags_dict(resource: Any) -> dict[str, str] | None:
    tags = getattr(resource, "tags", None)
    return dict(tags) if tags else None


def _name_from_id(resource_id: str) -> str:
    """Extract the resource name (last segment) from an ARM resource ID."""
    return resource_id.rsplit("/", 1)[-1] if resource_id else ""


def _rg_from_id(resource_id: str) -> str:
    """Extract the resource group from an ARM resource ID."""
    parts = resource_id.split("/")
    try:
        idx = [p.lower() for p in parts].index("resourcegroups")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return ""


# ---------------------------------------------------------------------------
# VM size -> vCPU / memory mapping (common sizes)
# ---------------------------------------------------------------------------

_VM_SPECS: dict[str, tuple[int, float]] = {
    "Standard_B1s": (1, 1.0),
    "Standard_B2s": (2, 4.0),
    "Standard_B2ms": (2, 8.0),
    "Standard_D2s_v5": (2, 8.0),
    "Standard_D4s_v5": (4, 16.0),
    "Standard_D8s_v5": (8, 32.0),
    "Standard_D16s_v5": (16, 64.0),
    "Standard_D32s_v5": (32, 128.0),
    "Standard_E2s_v5": (2, 16.0),
    "Standard_E4s_v5": (4, 32.0),
    "Standard_E8s_v5": (8, 64.0),
    "Standard_F2s_v2": (2, 4.0),
    "Standard_F4s_v2": (4, 8.0),
    "Standard_F8s_v2": (8, 16.0),
}


# ---------------------------------------------------------------------------
# Collector
# ---------------------------------------------------------------------------


class AzureCollector(BaseCollector):
    """Collects resources, metrics and billing data from a single Azure subscription."""

    def __init__(
        self,
        subscription_id: str,
        tenant_id: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        self.subscription_id = subscription_id
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret

        self._credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )

        # Management clients (lazy-ish, created once)
        self._compute = ComputeManagementClient(self._credential, subscription_id)
        self._network = NetworkManagementClient(self._credential, subscription_id)
        self._sql = SqlManagementClient(self._credential, subscription_id)
        self._storage = StorageManagementClient(self._credential, subscription_id)
        self._aks = ContainerServiceClient(self._credential, subscription_id)
        self._cost = CostManagementClient(self._credential)
        self._monitor = MonitorManagementClient(self._credential, subscription_id)
        self._resource = ResourceManagementClient(self._credential, subscription_id)

    # ------------------------------------------------------------------
    # BaseCollector interface
    # ------------------------------------------------------------------

    async def validate_credentials(self) -> bool:
        """Validate credentials by listing resource groups."""
        try:
            rgs = await _run_sync(_list_all, self._resource.resource_groups.list())
            logger.info(
                "azure_credentials_valid",
                subscription_id=self.subscription_id,
                resource_group_count=len(rgs),
            )
            return True
        except Exception:
            logger.error(
                "azure_credentials_invalid",
                subscription_id=self.subscription_id,
                exc_info=True,
            )
            return False

    async def collect_resources(self) -> list[CollectedResource]:
        """Discover all supported Azure resources in the subscription."""
        logger.info("azure_collection_started", subscription_id=self.subscription_id)

        tasks = [
            self._collect_vms(),
            self._collect_sql_databases(),
            self._collect_managed_disks(),
            self._collect_snapshots(),
            self._collect_load_balancers(),
            self._collect_public_ips(),
            self._collect_storage_accounts(),
            self._collect_aks_clusters(),
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        resources: list[CollectedResource] = []
        for idx, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(
                    "azure_collection_task_failed",
                    task_index=idx,
                    error=str(result),
                    exc_info=True,
                )
                continue
            resources.extend(result)

        logger.info(
            "azure_collection_completed",
            subscription_id=self.subscription_id,
            total_resources=len(resources),
        )
        return resources

    async def collect_billing(self, start_date: date, end_date: date) -> dict:
        """Fetch billing data via Azure Cost Management API."""
        scope = f"/subscriptions/{self.subscription_id}"
        body = {
            "type": "ActualCost",
            "timeframe": "Custom",
            "timePeriod": {
                "from": f"{start_date.isoformat()}T00:00:00Z",
                "to": f"{end_date.isoformat()}T23:59:59Z",
            },
            "dataset": {
                "granularity": "Daily",
                "aggregation": {
                    "totalCost": {"name": "Cost", "function": "Sum"},
                    "totalCostUSD": {"name": "CostUSD", "function": "Sum"},
                },
                "grouping": [
                    {"type": "Dimension", "name": "ServiceName"},
                    {"type": "Dimension", "name": "ResourceGroup"},
                ],
            },
        }

        try:
            result = await _run_sync(
                self._cost.query.usage, scope, body
            )
            rows = result.rows or []
            columns = [col.name for col in (result.columns or [])]

            billing: dict[str, Any] = {
                "subscription_id": self.subscription_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_cost": 0.0,
                "currency": "USD",
                "by_service": {},
                "by_resource_group": {},
                "daily": [],
            }

            for row in rows:
                entry = dict(zip(columns, row))
                cost = float(entry.get("CostUSD", entry.get("Cost", 0)))
                service = entry.get("ServiceName", "Unknown")
                rg = entry.get("ResourceGroup", "Unknown")

                billing["total_cost"] += cost
                billing["by_service"][service] = billing["by_service"].get(service, 0.0) + cost
                billing["by_resource_group"][rg] = billing["by_resource_group"].get(rg, 0.0) + cost

            billing["total_cost"] = round(billing["total_cost"], 2)
            logger.info(
                "azure_billing_collected",
                subscription_id=self.subscription_id,
                total_cost=billing["total_cost"],
                row_count=len(rows),
            )
            return billing

        except Exception:
            logger.error(
                "azure_billing_failed",
                subscription_id=self.subscription_id,
                exc_info=True,
            )
            return {
                "subscription_id": self.subscription_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "total_cost": 0.0,
                "currency": "USD",
                "error": "Failed to fetch billing data",
            }

    # ------------------------------------------------------------------
    # Resource collectors
    # ------------------------------------------------------------------

    @_azure_retry
    async def _collect_vms(self) -> list[CollectedResource]:
        vms = await _run_sync(_list_all, self._compute.virtual_machines.list_all())
        resources: list[CollectedResource] = []

        for vm in vms:
            vm_size = vm.hardware_profile.vm_size if vm.hardware_profile else None
            vcpus, memory_gb = _VM_SPECS.get(vm_size, (None, None)) if vm_size else (None, None)
            region = vm.location or "unknown"

            monthly_cost = await get_vm_monthly_cost(vm_size, region) if vm_size else 0.0

            resource = CollectedResource(
                resource_id=vm.id,
                resource_type=ResourceType.COMPUTE.value,
                provider_resource_type="azure:vm",
                region=region,
                name=vm.name,
                instance_type=vm_size,
                vcpus=vcpus,
                memory_gb=memory_gb,
                monthly_cost=monthly_cost,
                tags=_tags_dict(vm),
                metadata={
                    "provisioning_state": getattr(vm, "provisioning_state", None),
                    "os_type": (
                        vm.storage_profile.os_disk.os_type.value
                        if vm.storage_profile and vm.storage_profile.os_disk and vm.storage_profile.os_disk.os_type
                        else None
                    ),
                    "resource_group": _rg_from_id(vm.id),
                },
            )

            # Fetch VM metrics
            metrics = await self._collect_vm_metrics(vm.id)
            resource.metrics = metrics
            resources.append(resource)

        logger.info("azure_vms_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_sql_databases(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        servers = await _run_sync(_list_all, self._sql.servers.list())

        for server in servers:
            rg = _rg_from_id(server.id)
            dbs = await _run_sync(
                _list_all,
                self._sql.databases.list_by_server(rg, server.name),
            )
            for db in dbs:
                if db.name == "master":
                    continue
                sku = db.sku
                resources.append(
                    CollectedResource(
                        resource_id=db.id,
                        resource_type=ResourceType.DATABASE.value,
                        provider_resource_type="azure:sql_database",
                        region=db.location or server.location or "unknown",
                        name=f"{server.name}/{db.name}",
                        instance_type=sku.name if sku else None,
                        vcpus=sku.capacity if sku else None,
                        storage_gb=(
                            db.max_size_bytes / (1024**3) if db.max_size_bytes else None
                        ),
                        tags=_tags_dict(db),
                        metadata={
                            "server_name": server.name,
                            "sku_tier": sku.tier if sku else None,
                            "status": getattr(db, "status", None),
                            "resource_group": rg,
                        },
                    )
                )

        logger.info("azure_sql_databases_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_managed_disks(self) -> list[CollectedResource]:
        disks = await _run_sync(_list_all, self._compute.disks.list())
        resources: list[CollectedResource] = []

        for disk in disks:
            sku_name = disk.sku.name if disk.sku else "Standard_LRS"
            size_gb = disk.disk_size_gb or 0
            monthly_cost = estimate_disk_monthly_cost(sku_name, float(size_gb))

            resources.append(
                CollectedResource(
                    resource_id=disk.id,
                    resource_type=ResourceType.VOLUME.value,
                    provider_resource_type="azure:managed_disk",
                    region=disk.location or "unknown",
                    name=disk.name,
                    storage_gb=float(size_gb),
                    monthly_cost=monthly_cost,
                    tags=_tags_dict(disk),
                    metadata={
                        "sku": sku_name,
                        "disk_state": getattr(disk, "disk_state", None),
                        "os_type": disk.os_type.value if disk.os_type else None,
                        "resource_group": _rg_from_id(disk.id),
                    },
                )
            )

        logger.info("azure_managed_disks_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_snapshots(self) -> list[CollectedResource]:
        snapshots = await _run_sync(_list_all, self._compute.snapshots.list())
        resources: list[CollectedResource] = []

        for snap in snapshots:
            size_gb = snap.disk_size_gb or 0
            # Snapshot pricing ~$0.05/GB/month for standard
            monthly_cost = round(0.05 * size_gb, 2)

            resources.append(
                CollectedResource(
                    resource_id=snap.id,
                    resource_type=ResourceType.SNAPSHOT.value,
                    provider_resource_type="azure:snapshot",
                    region=snap.location or "unknown",
                    name=snap.name,
                    storage_gb=float(size_gb),
                    monthly_cost=monthly_cost,
                    tags=_tags_dict(snap),
                    metadata={
                        "source_resource_id": getattr(snap, "source_resource_id", None),
                        "time_created": (
                            snap.time_created.isoformat() if snap.time_created else None
                        ),
                        "resource_group": _rg_from_id(snap.id),
                    },
                )
            )

        logger.info("azure_snapshots_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_load_balancers(self) -> list[CollectedResource]:
        lbs = await _run_sync(_list_all, self._network.load_balancers.list_all())
        resources: list[CollectedResource] = []

        for lb in lbs:
            sku_name = lb.sku.name if lb.sku else "Basic"
            # Basic LB is free; Standard ~$18/month + rules
            monthly_cost = 18.0 if sku_name == "Standard" else 0.0

            resources.append(
                CollectedResource(
                    resource_id=lb.id,
                    resource_type=ResourceType.LOAD_BALANCER.value,
                    provider_resource_type="azure:load_balancer",
                    region=lb.location or "unknown",
                    name=lb.name,
                    monthly_cost=monthly_cost,
                    tags=_tags_dict(lb),
                    metadata={
                        "sku": sku_name,
                        "frontend_ip_count": (
                            len(lb.frontend_ip_configurations)
                            if lb.frontend_ip_configurations
                            else 0
                        ),
                        "rule_count": len(lb.load_balancing_rules) if lb.load_balancing_rules else 0,
                        "resource_group": _rg_from_id(lb.id),
                    },
                )
            )

        logger.info("azure_load_balancers_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_public_ips(self) -> list[CollectedResource]:
        ips = await _run_sync(_list_all, self._network.public_ip_addresses.list_all())
        resources: list[CollectedResource] = []

        for ip in ips:
            sku_name = ip.sku.name if ip.sku else "Basic"
            # Static standard IP ~$3.65/month; basic static ~$2.63
            if ip.public_ip_allocation_method == "Static":
                monthly_cost = 3.65 if sku_name == "Standard" else 2.63
            else:
                monthly_cost = 0.0

            resources.append(
                CollectedResource(
                    resource_id=ip.id,
                    resource_type=ResourceType.IP_ADDRESS.value,
                    provider_resource_type="azure:public_ip",
                    region=ip.location or "unknown",
                    name=ip.name,
                    monthly_cost=monthly_cost,
                    tags=_tags_dict(ip),
                    metadata={
                        "sku": sku_name,
                        "allocation_method": ip.public_ip_allocation_method,
                        "ip_address": ip.ip_address,
                        "associated": ip.ip_configuration is not None,
                        "resource_group": _rg_from_id(ip.id),
                    },
                )
            )

        logger.info("azure_public_ips_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_storage_accounts(self) -> list[CollectedResource]:
        accounts = await _run_sync(_list_all, self._storage.storage_accounts.list())
        resources: list[CollectedResource] = []

        for acct in accounts:
            sku_name = acct.sku.name if acct.sku else "Standard_LRS"
            resources.append(
                CollectedResource(
                    resource_id=acct.id,
                    resource_type=ResourceType.STORAGE.value,
                    provider_resource_type="azure:storage_account",
                    region=acct.location or "unknown",
                    name=acct.name,
                    tags=_tags_dict(acct),
                    metadata={
                        "sku": sku_name,
                        "kind": getattr(acct, "kind", None),
                        "access_tier": (
                            acct.access_tier.value if acct.access_tier else None
                        ),
                        "resource_group": _rg_from_id(acct.id),
                    },
                )
            )

        logger.info("azure_storage_accounts_collected", count=len(resources))
        return resources

    @_azure_retry
    async def _collect_aks_clusters(self) -> list[CollectedResource]:
        clusters = await _run_sync(
            _list_all, self._aks.managed_clusters.list()
        )
        resources: list[CollectedResource] = []

        for cluster in clusters:
            total_nodes = 0
            node_pools_info: list[dict[str, Any]] = []
            if cluster.agent_pool_profiles:
                for pool in cluster.agent_pool_profiles:
                    count = pool.count or 0
                    total_nodes += count
                    node_pools_info.append({
                        "name": pool.name,
                        "vm_size": pool.vm_size,
                        "count": count,
                        "mode": getattr(pool, "mode", None),
                    })

            resources.append(
                CollectedResource(
                    resource_id=cluster.id,
                    resource_type=ResourceType.KUBERNETES.value,
                    provider_resource_type="azure:aks_cluster",
                    region=cluster.location or "unknown",
                    name=cluster.name,
                    tags=_tags_dict(cluster),
                    metadata={
                        "kubernetes_version": cluster.kubernetes_version,
                        "node_count": total_nodes,
                        "node_pools": node_pools_info,
                        "provisioning_state": getattr(cluster, "provisioning_state", None),
                        "resource_group": _rg_from_id(cluster.id),
                    },
                )
            )

        logger.info("azure_aks_clusters_collected", count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    async def _collect_vm_metrics(self, resource_id: str) -> list[CollectedMetric]:
        """Fetch Azure Monitor metrics for a VM over the last 30 days."""
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=30)
        timespan = f"{start.isoformat()}/{now.isoformat()}"
        interval = "PT1H"

        metric_definitions: list[tuple[str, str]] = [
            ("Percentage CPU", "cpu_utilization"),
            ("Available Memory Bytes", "memory_available_bytes"),
            ("Network In Total", "network_in"),
            ("Network Out Total", "network_out"),
            ("OS Disk IOPS Consumed Percentage", "disk_iops"),
        ]
        metric_names = ",".join(m[0] for m in metric_definitions)

        try:
            result = await _run_sync(
                self._monitor.metrics.list,
                resource_id,
                timespan=timespan,
                interval=interval,
                metricnames=metric_names,
                aggregation="Average,Maximum,Minimum",
            )

            collected: list[CollectedMetric] = []
            azure_name_to_local = {az: local for az, local in metric_definitions}

            for metric in result.value:
                local_name = azure_name_to_local.get(metric.name.value)
                if local_name is None:
                    continue

                values: list[float] = []
                for ts in metric.timeseries:
                    for dp in ts.data:
                        if dp.average is not None:
                            values.append(dp.average)

                if not values:
                    continue

                values_sorted = sorted(values)
                p95_idx = int(len(values_sorted) * 0.95)

                collected.append(
                    CollectedMetric(
                        metric_name=local_name,
                        avg_value=round(sum(values) / len(values), 4),
                        max_value=round(max(values), 4),
                        min_value=round(min(values), 4),
                        p95_value=round(values_sorted[min(p95_idx, len(values_sorted) - 1)], 4),
                        period_days=30,
                    )
                )

            return collected

        except Exception:
            logger.warning(
                "azure_vm_metrics_failed",
                resource_id=resource_id,
                exc_info=True,
            )
            return []
