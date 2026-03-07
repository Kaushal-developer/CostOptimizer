"""GCP cloud resource collector using google-cloud SDK."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any

from google.api_core.exceptions import GoogleAPICallError, NotFound, PermissionDenied
from google.auth import default as google_default_credentials
from google.cloud import bigquery, compute_v1, container_v1, monitoring_v2, storage
from google.cloud.monitoring_v2 import types as monitoring_types
from google.cloud.sql_v1beta4 import SqlInstancesServiceClient
from google.oauth2 import service_account
from google.protobuf.json_format import MessageToDict
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.core.logging import logger
from src.ingestion.base import BaseCollector, CollectedMetric, CollectedResource
from src.ingestion.gcp.pricing import GCPPricingHelper
from src.models.resource import ResourceType

_RETRY_DECORATOR = retry(
    retry=retry_if_exception_type(GoogleAPICallError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)


class GCPCollector(BaseCollector):
    """Collects resources and metrics from Google Cloud Platform."""

    def __init__(
        self,
        project_id: str,
        credentials_path: str | None = None,
        billing_dataset: str = "billing_export",
        billing_table: str = "gcp_billing_export_v1",
        metric_period_days: int = 30,
    ) -> None:
        self.project_id = project_id
        self.metric_period_days = metric_period_days
        self.billing_dataset = billing_dataset
        self.billing_table = billing_table
        self._pricing = GCPPricingHelper(project_id)

        if credentials_path:
            self._credentials = service_account.Credentials.from_service_account_file(
                credentials_path,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
        else:
            self._credentials, _ = google_default_credentials(
                scopes=["https://www.googleapis.com/auth/cloud-platform"]
            )

        self._compute_client = compute_v1.InstancesClient(credentials=self._credentials)
        self._disks_client = compute_v1.DisksClient(credentials=self._credentials)
        self._snapshots_client = compute_v1.SnapshotsClient(credentials=self._credentials)
        self._addresses_client = compute_v1.AddressesClient(credentials=self._credentials)
        self._forwarding_client = compute_v1.ForwardingRulesClient(credentials=self._credentials)
        self._storage_client = storage.Client(project=project_id, credentials=self._credentials)
        self._monitoring_client = monitoring_v2.MetricServiceClient(credentials=self._credentials)
        self._bq_client = bigquery.Client(project=project_id, credentials=self._credentials)
        self._container_client = container_v1.ClusterManagerClient(credentials=self._credentials)
        self._sql_client = SqlInstancesServiceClient(credentials=self._credentials)

        self._log = logger.bind(provider="gcp", project=project_id)

    # ------------------------------------------------------------------
    # BaseCollector interface
    # ------------------------------------------------------------------

    async def validate_credentials(self) -> bool:
        """Validate GCP credentials by listing a single compute zone."""
        try:
            zones_client = compute_v1.ZonesClient(credentials=self._credentials)
            await asyncio.to_thread(
                lambda: list(zones_client.list(project=self.project_id, max_results=1))
            )
            self._log.info("gcp_credentials_valid")
            return True
        except Exception as exc:
            self._log.error("gcp_credentials_invalid", error=str(exc))
            return False

    async def collect_resources(self) -> list[CollectedResource]:
        """Discover all supported GCP resources in the project."""
        collectors = [
            self._collect_compute_instances,
            self._collect_cloud_sql,
            self._collect_persistent_disks,
            self._collect_snapshots,
            self._collect_forwarding_rules,
            self._collect_static_ips,
            self._collect_gcs_buckets,
            self._collect_gke_clusters,
        ]
        tasks = [c() for c in collectors]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        resources: list[CollectedResource] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                self._log.error(
                    "resource_collection_failed",
                    collector=collectors[i].__name__,
                    error=str(result),
                )
            else:
                resources.extend(result)

        self._log.info("resource_collection_complete", total=len(resources))

        # Enrich with metrics
        await self._attach_metrics(resources)
        return resources

    async def collect_billing(self, start_date: date, end_date: date) -> dict:
        """Query BigQuery billing export for cost data."""
        query = f"""
            SELECT
                service.description AS service,
                sku.description AS sku,
                location.region AS region,
                SUM(cost) AS total_cost,
                SUM(usage.amount) AS total_usage,
                usage.unit AS usage_unit,
                currency
            FROM `{self.project_id}.{self.billing_dataset}.{self.billing_table}`
            WHERE usage_start_time >= @start_date
              AND usage_start_time < @end_date
              AND project.id = @project_id
            GROUP BY service, sku, region, usage_unit, currency
            ORDER BY total_cost DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("start_date", "DATE", start_date.isoformat()),
                bigquery.ScalarQueryParameter("end_date", "DATE", end_date.isoformat()),
                bigquery.ScalarQueryParameter("project_id", "STRING", self.project_id),
            ]
        )
        try:
            rows = await asyncio.to_thread(
                lambda: list(
                    self._bq_client.query(query, job_config=job_config).result()
                )
            )
            billing: dict[str, Any] = {
                "project_id": self.project_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "line_items": [dict(row) for row in rows],
                "total_cost": sum(row["total_cost"] for row in rows),
            }
            self._log.info("billing_collected", items=len(rows), total=billing["total_cost"])
            return billing
        except Exception as exc:
            self._log.error("billing_query_failed", error=str(exc))
            return {
                "project_id": self.project_id,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "line_items": [],
                "total_cost": 0.0,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Resource collectors
    # ------------------------------------------------------------------

    @_RETRY_DECORATOR
    async def _collect_compute_instances(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        agg_list = await asyncio.to_thread(
            lambda: self._compute_client.aggregated_list(project=self.project_id)
        )
        for zone_scope, response in agg_list:
            if not response.instances:
                continue
            zone = zone_scope.rsplit("/", 1)[-1]
            region = "-".join(zone.split("-")[:-1])
            for inst in response.instances:
                machine_type_short = inst.machine_type.rsplit("/", 1)[-1]
                specs = self._pricing.machine_type_specs(machine_type_short)
                resources.append(
                    CollectedResource(
                        resource_id=str(inst.id),
                        resource_type=ResourceType.COMPUTE.value,
                        provider_resource_type="gce:instance",
                        region=region,
                        name=inst.name,
                        instance_type=machine_type_short,
                        vcpus=specs.get("vcpus"),
                        memory_gb=specs.get("memory_gb"),
                        monthly_cost=self._pricing.estimate_instance_cost(
                            machine_type_short, region
                        ),
                        tags=dict(inst.labels) if inst.labels else None,
                        metadata={
                            "zone": zone,
                            "status": inst.status,
                            "network_interfaces": len(inst.network_interfaces),
                        },
                    )
                )
        self._log.info("compute_instances_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_cloud_sql(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        request = {"project": self.project_id}
        instances = await asyncio.to_thread(lambda: self._sql_client.list(request=request))
        for inst in getattr(instances, "items", []) or []:
            settings = inst.settings
            region = inst.region
            tier = settings.tier if settings else "unknown"
            storage_gb = (
                settings.data_disk_size_gb if settings else None
            )
            resources.append(
                CollectedResource(
                    resource_id=inst.name,
                    resource_type=ResourceType.DATABASE.value,
                    provider_resource_type="cloudsql:instance",
                    region=region,
                    name=inst.name,
                    instance_type=tier,
                    storage_gb=float(storage_gb) if storage_gb else None,
                    monthly_cost=self._pricing.estimate_sql_cost(tier, region),
                    metadata={
                        "database_version": inst.database_version,
                        "state": inst.state,
                        "ha": getattr(
                            settings, "availability_type", None
                        ),
                    },
                )
            )
        self._log.info("cloud_sql_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_persistent_disks(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        agg_list = await asyncio.to_thread(
            lambda: self._disks_client.aggregated_list(project=self.project_id)
        )
        for zone_scope, response in agg_list:
            if not response.disks:
                continue
            zone = zone_scope.rsplit("/", 1)[-1]
            region = "-".join(zone.split("-")[:-1])
            for disk in response.disks:
                resources.append(
                    CollectedResource(
                        resource_id=str(disk.id),
                        resource_type=ResourceType.VOLUME.value,
                        provider_resource_type="gce:disk",
                        region=region,
                        name=disk.name,
                        storage_gb=float(disk.size_gb) if disk.size_gb else None,
                        monthly_cost=self._pricing.estimate_disk_cost(
                            disk.type_.rsplit("/", 1)[-1],
                            float(disk.size_gb) if disk.size_gb else 0,
                            region,
                        ),
                        tags=dict(disk.labels) if disk.labels else None,
                        metadata={
                            "zone": zone,
                            "disk_type": disk.type_.rsplit("/", 1)[-1],
                            "status": disk.status,
                            "users": list(disk.users) if disk.users else [],
                        },
                    )
                )
        self._log.info("persistent_disks_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_snapshots(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        snapshots = await asyncio.to_thread(
            lambda: self._snapshots_client.list(project=self.project_id)
        )
        for snap in snapshots:
            storage_gb = float(snap.storage_bytes or 0) / (1024**3)
            resources.append(
                CollectedResource(
                    resource_id=str(snap.id),
                    resource_type=ResourceType.SNAPSHOT.value,
                    provider_resource_type="gce:snapshot",
                    region="global",
                    name=snap.name,
                    storage_gb=round(storage_gb, 2),
                    monthly_cost=self._pricing.estimate_snapshot_cost(storage_gb),
                    tags=dict(snap.labels) if snap.labels else None,
                    metadata={
                        "status": snap.status,
                        "source_disk": snap.source_disk,
                        "created": snap.creation_timestamp,
                    },
                )
            )
        self._log.info("snapshots_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_forwarding_rules(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        agg_list = await asyncio.to_thread(
            lambda: self._forwarding_client.aggregated_list(project=self.project_id)
        )
        for scope, response in agg_list:
            if not response.forwarding_rules:
                continue
            region = scope.rsplit("/", 1)[-1]
            for rule in response.forwarding_rules:
                resources.append(
                    CollectedResource(
                        resource_id=str(rule.id),
                        resource_type=ResourceType.LOAD_BALANCER.value,
                        provider_resource_type="gce:forwarding_rule",
                        region=region,
                        name=rule.name,
                        monthly_cost=self._pricing.estimate_lb_cost(region),
                        metadata={
                            "ip_address": rule.I_p_address,
                            "ip_protocol": rule.I_p_protocol,
                            "port_range": rule.port_range,
                            "load_balancing_scheme": rule.load_balancing_scheme,
                            "target": rule.target,
                        },
                    )
                )
        self._log.info("forwarding_rules_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_static_ips(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        agg_list = await asyncio.to_thread(
            lambda: self._addresses_client.aggregated_list(project=self.project_id)
        )
        for scope, response in agg_list:
            if not response.addresses:
                continue
            region = scope.rsplit("/", 1)[-1]
            for addr in response.addresses:
                in_use = addr.status == "IN_USE"
                resources.append(
                    CollectedResource(
                        resource_id=str(addr.id),
                        resource_type=ResourceType.IP_ADDRESS.value,
                        provider_resource_type="gce:address",
                        region=region,
                        name=addr.name,
                        monthly_cost=self._pricing.estimate_static_ip_cost(in_use),
                        metadata={
                            "address": addr.address,
                            "status": addr.status,
                            "address_type": addr.address_type,
                            "users": list(addr.users) if addr.users else [],
                        },
                    )
                )
        self._log.info("static_ips_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_gcs_buckets(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        buckets = await asyncio.to_thread(lambda: list(self._storage_client.list_buckets()))
        for bucket in buckets:
            resources.append(
                CollectedResource(
                    resource_id=bucket.id,
                    resource_type=ResourceType.STORAGE.value,
                    provider_resource_type="gcs:bucket",
                    region=bucket.location.lower() if bucket.location else "us",
                    name=bucket.name,
                    tags=dict(bucket.labels) if bucket.labels else None,
                    metadata={
                        "storage_class": bucket.storage_class,
                        "location_type": bucket.location_type,
                        "versioning": bucket.versioning_enabled,
                        "created": bucket.time_created.isoformat() if bucket.time_created else None,
                    },
                )
            )
        self._log.info("gcs_buckets_collected", count=len(resources))
        return resources

    @_RETRY_DECORATOR
    async def _collect_gke_clusters(self) -> list[CollectedResource]:
        resources: list[CollectedResource] = []
        parent = f"projects/{self.project_id}/locations/-"
        response = await asyncio.to_thread(
            lambda: self._container_client.list_clusters(parent=parent)
        )
        for cluster in response.clusters or []:
            total_nodes = sum(
                (np.initial_node_count or 0) for np in (cluster.node_pools or [])
            )
            resources.append(
                CollectedResource(
                    resource_id=cluster.self_link,
                    resource_type=ResourceType.KUBERNETES.value,
                    provider_resource_type="gke:cluster",
                    region=cluster.location,
                    name=cluster.name,
                    metadata={
                        "status": cluster.status.name if cluster.status else None,
                        "node_pools": len(cluster.node_pools or []),
                        "total_nodes": total_nodes,
                        "cluster_version": cluster.current_master_version,
                        "autopilot": bool(
                            cluster.autopilot and cluster.autopilot.enabled
                        ),
                    },
                )
            )
        self._log.info("gke_clusters_collected", count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # Cloud Monitoring metrics
    # ------------------------------------------------------------------

    async def _attach_metrics(self, resources: list[CollectedResource]) -> None:
        """Fetch Cloud Monitoring metrics and attach to resources."""
        compute_resources = [
            r for r in resources if r.resource_type == ResourceType.COMPUTE.value
        ]
        if not compute_resources:
            return

        metric_defs = [
            ("compute.googleapis.com/instance/cpu/utilization", "cpu_utilization"),
            ("compute.googleapis.com/instance/network/received_bytes_count", "network_in"),
            ("compute.googleapis.com/instance/network/sent_bytes_count", "network_out"),
            ("compute.googleapis.com/instance/disk/read_ops_count", "disk_read_iops"),
            ("compute.googleapis.com/instance/disk/write_ops_count", "disk_write_iops"),
        ]

        resource_map = {r.name: r for r in compute_resources if r.name}
        now = datetime.now(timezone.utc)
        start = now - timedelta(days=self.metric_period_days)

        for gcp_metric, local_name in metric_defs:
            try:
                metric = await self._query_monitoring_metric(
                    gcp_metric, start, now, resource_map.keys()
                )
                for instance_name, values in metric.items():
                    if instance_name in resource_map and values:
                        resource_map[instance_name].metrics.append(
                            CollectedMetric(
                                metric_name=local_name,
                                avg_value=sum(values) / len(values),
                                max_value=max(values),
                                min_value=min(values),
                                p95_value=sorted(values)[int(len(values) * 0.95)]
                                if len(values) >= 20
                                else None,
                                period_days=self.metric_period_days,
                            )
                        )
            except Exception as exc:
                self._log.warning(
                    "metric_fetch_failed", metric=gcp_metric, error=str(exc)
                )

    async def _query_monitoring_metric(
        self,
        metric_type: str,
        start: datetime,
        end: datetime,
        instance_names: Any,
    ) -> dict[str, list[float]]:
        """Query a single metric from Cloud Monitoring, returning values per instance name."""
        project_name = f"projects/{self.project_id}"
        interval = monitoring_types.TimeInterval(
            start_time=start,
            end_time=end,
        )
        names_filter = " OR ".join(
            f'resource.labels.instance_name = "{n}"' for n in instance_names
        )
        filter_str = (
            f'metric.type = "{metric_type}" AND ({names_filter})'
        )
        request = monitoring_types.ListTimeSeriesRequest(
            name=project_name,
            filter=filter_str,
            interval=interval,
            view=monitoring_types.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )
        results: dict[str, list[float]] = {}
        time_series = await asyncio.to_thread(
            lambda: list(self._monitoring_client.list_time_series(request=request))
        )
        for ts in time_series:
            inst_name = ts.resource.labels.get("instance_name", "")
            values = []
            for point in ts.points:
                val = point.value.double_value or point.value.int64_value
                values.append(float(val))
            results.setdefault(inst_name, []).extend(values)
        return results
