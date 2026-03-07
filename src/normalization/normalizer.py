"""
Normalization engine that converts cloud-specific collected resources
into unified database models for cross-cloud analysis.
"""

from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from src.core.logging import logger
from src.ingestion.base import CollectedResource, CollectedMetric
from src.models.cloud_account import CloudAccount, CloudProvider
from src.models.resource import Resource, ResourceMetric, ResourceType, ResourceStatus


# Map provider resource type prefixes to our unified ResourceType
RESOURCE_TYPE_MAP = {
    # AWS
    "ec2:instance": ResourceType.COMPUTE,
    "rds:instance": ResourceType.DATABASE,
    "ebs:volume": ResourceType.VOLUME,
    "ebs:snapshot": ResourceType.SNAPSHOT,
    "elb:load_balancer": ResourceType.LOAD_BALANCER,
    "ec2:elastic_ip": ResourceType.IP_ADDRESS,
    "s3:bucket": ResourceType.STORAGE,
    "eks:cluster": ResourceType.KUBERNETES,
    # Azure
    "azure:vm": ResourceType.COMPUTE,
    "azure:sql_database": ResourceType.DATABASE,
    "azure:managed_disk": ResourceType.VOLUME,
    "azure:snapshot": ResourceType.SNAPSHOT,
    "azure:load_balancer": ResourceType.LOAD_BALANCER,
    "azure:public_ip": ResourceType.IP_ADDRESS,
    "azure:storage_account": ResourceType.STORAGE,
    "azure:aks_cluster": ResourceType.KUBERNETES,
    # GCP
    "gce:instance": ResourceType.COMPUTE,
    "cloudsql:instance": ResourceType.DATABASE,
    "gce:disk": ResourceType.VOLUME,
    "gce:snapshot": ResourceType.SNAPSHOT,
    "gce:forwarding_rule": ResourceType.LOAD_BALANCER,
    "gce:address": ResourceType.IP_ADDRESS,
    "gcs:bucket": ResourceType.STORAGE,
    "gke:cluster": ResourceType.KUBERNETES,
}


def map_resource_type(provider_resource_type: str) -> ResourceType:
    """Map a provider-specific resource type to our unified enum."""
    mapped = RESOURCE_TYPE_MAP.get(provider_resource_type)
    if mapped:
        return mapped
    # Fallback heuristics
    prt = provider_resource_type.lower()
    if "instance" in prt or "vm" in prt:
        return ResourceType.COMPUTE
    if "disk" in prt or "volume" in prt:
        return ResourceType.VOLUME
    if "snapshot" in prt:
        return ResourceType.SNAPSHOT
    if "bucket" in prt or "storage" in prt:
        return ResourceType.STORAGE
    if "lb" in prt or "load_balancer" in prt or "forwarding" in prt:
        return ResourceType.LOAD_BALANCER
    if "ip" in prt or "address" in prt:
        return ResourceType.IP_ADDRESS
    if "sql" in prt or "database" in prt or "rds" in prt:
        return ResourceType.DATABASE
    if "kubernetes" in prt or "eks" in prt or "aks" in prt or "gke" in prt:
        return ResourceType.KUBERNETES
    return ResourceType.COMPUTE


class ResourceNormalizer:
    """Normalizes collected resources into the unified database model."""

    def __init__(self, db: AsyncSession, cloud_account: CloudAccount):
        self.db = db
        self.cloud_account = cloud_account

    async def normalize_and_persist(
        self, collected: list[CollectedResource]
    ) -> list[Resource]:
        """Normalize collected resources and upsert into database."""
        persisted = []
        for cr in collected:
            try:
                resource = await self._upsert_resource(cr)
                await self._upsert_metrics(resource, cr.metrics)
                persisted.append(resource)
            except Exception:
                logger.exception(
                    "Failed to normalize resource",
                    resource_id=cr.resource_id,
                    provider=self.cloud_account.provider.value,
                )
        await self.db.flush()
        logger.info(
            "Normalization complete",
            account_id=self.cloud_account.id,
            total=len(collected),
            persisted=len(persisted),
        )
        return persisted

    async def _upsert_resource(self, cr: CollectedResource) -> Resource:
        """Insert or update a resource record."""
        result = await self.db.execute(
            select(Resource).where(
                Resource.cloud_account_id == self.cloud_account.id,
                Resource.resource_id == cr.resource_id,
            )
        )
        resource = result.scalar_one_or_none()

        resource_type = map_resource_type(cr.provider_resource_type)
        now = datetime.now(timezone.utc)

        if resource is None:
            resource = Resource(
                cloud_account_id=self.cloud_account.id,
                resource_id=cr.resource_id,
                resource_type=resource_type,
                provider_resource_type=cr.provider_resource_type,
                region=cr.region,
                name=cr.name,
                instance_type=cr.instance_type,
                vcpus=cr.vcpus,
                memory_gb=cr.memory_gb,
                storage_gb=cr.storage_gb,
                monthly_cost=cr.monthly_cost,
                tags=cr.tags,
                metadata_=cr.metadata,
                last_seen_at=now,
            )
            self.db.add(resource)
        else:
            resource.resource_type = resource_type
            resource.provider_resource_type = cr.provider_resource_type
            resource.region = cr.region
            resource.name = cr.name
            resource.instance_type = cr.instance_type
            resource.vcpus = cr.vcpus
            resource.memory_gb = cr.memory_gb
            resource.storage_gb = cr.storage_gb
            resource.monthly_cost = cr.monthly_cost
            resource.tags = cr.tags
            resource.metadata_ = cr.metadata
            resource.last_seen_at = now

        return resource

    async def _upsert_metrics(
        self, resource: Resource, metrics: list[CollectedMetric]
    ) -> None:
        """Replace metrics for a resource with fresh collection."""
        # Delete existing metrics for this resource
        existing = await self.db.execute(
            select(ResourceMetric).where(ResourceMetric.resource_id == resource.id)
        )
        for old in existing.scalars().all():
            await self.db.delete(old)

        for m in metrics:
            metric = ResourceMetric(
                resource_id=resource.id,
                metric_name=m.metric_name,
                avg_value=m.avg_value,
                max_value=m.max_value,
                min_value=m.min_value,
                p95_value=m.p95_value,
                period_days=m.period_days,
            )
            self.db.add(metric)

    async def mark_stale_resources(self, current_ids: set[str]) -> int:
        """Mark resources not seen in this collection cycle as potentially zombie."""
        result = await self.db.execute(
            select(Resource).where(
                Resource.cloud_account_id == self.cloud_account.id,
                Resource.resource_id.notin_(current_ids),
                Resource.status != ResourceStatus.ZOMBIE,
            )
        )
        stale = result.scalars().all()
        for r in stale:
            r.status = ResourceStatus.ZOMBIE
        return len(stale)
