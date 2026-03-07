"""Service to sync cloud account resources into the database."""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.cloud_account import CloudAccount, AccountStatus
from src.models.resource import Resource, ResourceMetric, ResourceType, ResourceStatus
from src.ingestion.base import CollectedResource

logger = structlog.get_logger(__name__)

# Map collector resource_type strings to the DB enum
_TYPE_MAP = {
    "COMPUTE": ResourceType.COMPUTE,
    "DATABASE": ResourceType.DATABASE,
    "STORAGE": ResourceType.STORAGE,
    "NETWORK": ResourceType.NETWORK,
    "KUBERNETES": ResourceType.KUBERNETES,
    "SNAPSHOT": ResourceType.SNAPSHOT,
    "VOLUME": ResourceType.VOLUME,
    "LOAD_BALANCER": ResourceType.LOAD_BALANCER,
    "IP_ADDRESS": ResourceType.IP_ADDRESS,
}


async def run_sync(account: CloudAccount, db: AsyncSession) -> dict:
    """Run a full sync for the given cloud account. Returns summary stats."""
    log = logger.bind(account_id=account.id, provider=account.provider.value)
    log.info("sync_started")

    try:
        collector = _build_collector(account)

        # Validate credentials first
        valid = await collector.validate_credentials()
        if not valid:
            account.status = AccountStatus.ERROR
            account.last_error = "Invalid credentials"
            account.last_sync_at = datetime.now(timezone.utc)
            await db.flush()
            return {"status": "error", "error": "Invalid credentials", "resources": 0}

        # Collect resources
        collected = await collector.collect_resources()
        log.info("resources_collected", count=len(collected))

        # Load existing resources for this account (keyed by resource_id)
        existing_result = await db.execute(
            select(Resource).where(Resource.cloud_account_id == account.id)
        )
        existing_map: dict[str, Resource] = {
            r.resource_id: r for r in existing_result.scalars().all()
        }

        # Track which resource_ids we see in this sync
        seen_resource_ids: set[str] = set()
        resource_map: list[tuple[Resource, CollectedResource]] = []

        for cr in collected:
            seen_resource_ids.add(cr.resource_id)

            if cr.resource_id in existing_map:
                # UPDATE existing resource — preserve the row, update fields
                resource = existing_map[cr.resource_id]
                _update_resource(resource, cr)
                resource_map.append((resource, cr))
            else:
                # INSERT new resource
                resource = _collected_to_model(cr, account.id)
                db.add(resource)
                resource_map.append((resource, cr))

        # Mark resources that disappeared as stale (don't delete them)
        for rid, resource in existing_map.items():
            if rid not in seen_resource_ids:
                resource.status = ResourceStatus.ZOMBIE
                resource.last_seen_at = resource.last_seen_at  # keep original

        await db.flush()  # Assigns resource.id to new Resources

        # Upsert metrics: delete old metrics for synced resources, insert fresh ones
        metrics_count = 0
        for resource, cr in resource_map:
            if cr.metrics:
                # Remove stale metrics for this resource
                await db.execute(
                    delete(ResourceMetric).where(ResourceMetric.resource_id == resource.id)
                )
                for cm in cr.metrics:
                    metric = ResourceMetric(
                        resource_id=resource.id,
                        metric_name=cm.metric_name,
                        avg_value=cm.avg_value,
                        max_value=cm.max_value,
                        min_value=cm.min_value,
                        p95_value=cm.p95_value,
                        period_days=cm.period_days,
                    )
                    db.add(metric)
                    metrics_count += 1

        # Update account status
        account.status = AccountStatus.CONNECTED
        account.last_sync_at = datetime.now(timezone.utc)
        account.last_error = None
        await db.flush()
        log.info("metrics_persisted", count=metrics_count)

        total_cost = sum(cr.monthly_cost for cr in collected)
        log.info("sync_complete", resources=len(collected), total_monthly_cost=round(total_cost, 2))

        # Run optimization to generate recommendations
        from src.services.optimization_service import run_optimization
        opt_result = await run_optimization(account, db)

        return {
            "status": "success",
            "resources": len(collected),
            "total_monthly_cost": round(total_cost, 2),
            "recommendations_created": opt_result.get("recommendations_created", 0),
        }

    except Exception as exc:
        log.error("sync_failed", error=str(exc))
        account.status = AccountStatus.ERROR
        account.last_error = str(exc)[:500]
        account.last_sync_at = datetime.now(timezone.utc)
        await db.flush()
        return {"status": "error", "error": str(exc), "resources": 0}


def _build_collector(account: CloudAccount):
    """Build the appropriate collector based on provider and credentials."""
    provider = account.provider.value

    if provider == "aws":
        from src.ingestion.aws.collector import AWSCollector

        regions = [account.aws_region] if account.aws_region else None

        if account.aws_access_key_id:
            return AWSCollector(
                access_key_id=account.aws_access_key_id,
                secret_access_key=account.aws_secret_access_key,
                regions=regions,
            )
        elif account.aws_role_arn:
            return AWSCollector(
                role_arn=account.aws_role_arn,
                external_id=account.aws_external_id,
                regions=regions,
            )
        else:
            raise ValueError("AWS account missing credentials")

    elif provider == "azure":
        raise NotImplementedError("Azure sync not yet configured — add azure credentials first")

    elif provider == "gcp":
        raise NotImplementedError("GCP sync not yet configured — add gcp credentials first")

    else:
        raise ValueError(f"Unknown provider: {provider}")


def _update_resource(resource: Resource, cr: CollectedResource) -> None:
    """Update an existing resource row with fresh data from collector."""
    resource.resource_type = _TYPE_MAP.get(cr.resource_type, ResourceType.COMPUTE)
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
    resource.last_seen_at = datetime.now(timezone.utc)

    # Re-evaluate status
    meta_state = (cr.metadata or {}).get("state", "").lower()
    if meta_state in ("stopped", "deallocated"):
        resource.status = ResourceStatus.IDLE
    elif meta_state == "available" and cr.resource_type == "VOLUME":
        attachments = (cr.metadata or {}).get("attachments", [])
        if not attachments or all(a is None for a in attachments):
            resource.status = ResourceStatus.ZOMBIE
        else:
            resource.status = ResourceStatus.ACTIVE
    else:
        resource.status = ResourceStatus.ACTIVE


def _collected_to_model(cr: CollectedResource, cloud_account_id: int) -> Resource:
    """Convert a CollectedResource dataclass into a Resource ORM model."""
    resource_type = _TYPE_MAP.get(cr.resource_type, ResourceType.COMPUTE)

    # Determine status based on metadata
    status = ResourceStatus.ACTIVE
    meta_state = (cr.metadata or {}).get("state", "").lower()
    if meta_state in ("stopped", "deallocated"):
        status = ResourceStatus.IDLE
    elif meta_state == "available" and cr.resource_type == "VOLUME":
        # Unattached volumes
        attachments = (cr.metadata or {}).get("attachments", [])
        if not attachments or all(a is None for a in attachments):
            status = ResourceStatus.ZOMBIE

    return Resource(
        cloud_account_id=cloud_account_id,
        resource_id=cr.resource_id,
        resource_type=resource_type,
        provider_resource_type=cr.provider_resource_type,
        region=cr.region,
        status=status,
        name=cr.name,
        instance_type=cr.instance_type,
        vcpus=cr.vcpus,
        memory_gb=cr.memory_gb,
        storage_gb=cr.storage_gb,
        monthly_cost=cr.monthly_cost,
        tags=cr.tags,
        metadata_=cr.metadata,
        last_seen_at=datetime.now(timezone.utc),
    )
