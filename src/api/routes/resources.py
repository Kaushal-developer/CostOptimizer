from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.cloud_account import CloudAccount
from src.models.resource import Resource, ResourceMetric
from src.schemas.resource import (
    ResourceResponse,
    ResourceDetail,
    ResourceList,
    ResourceMetricResponse,
    ResourceMetricHistory,
    ResourceMetricHistoryPoint,
)

router = APIRouter(prefix="/resources", tags=["resources"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


def _tenant_resource_query(tenant_id: int):
    """Base query that joins Resource -> CloudAccount for tenant isolation."""
    return (
        select(Resource)
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tenant_id)
    )


@router.get("", response_model=ResourceList)
async def list_resources(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    resource_type: str | None = None,
    status_filter: str | None = Query(None, alias="status"),
    region: str | None = None,
    cloud_account_id: int | None = None,
    min_cost: float | None = None,
    max_cost: float | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    base = _tenant_resource_query(tid)

    if resource_type:
        base = base.where(Resource.resource_type == resource_type)
    if status_filter:
        base = base.where(Resource.status == status_filter)
    if region:
        base = base.where(Resource.region == region)
    if cloud_account_id:
        base = base.where(Resource.cloud_account_id == cloud_account_id)
    if min_cost is not None:
        base = base.where(Resource.monthly_cost >= min_cost)
    if max_cost is not None:
        base = base.where(Resource.monthly_cost <= max_cost)

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = base.order_by(Resource.monthly_cost.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return ResourceList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{resource_id}", response_model=ResourceDetail)
async def get_resource(
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    q = _tenant_resource_query(tid).where(Resource.id == resource_id).options(selectinload(Resource.metrics))
    result = await db.execute(q)
    resource = result.scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")
    return resource


@router.get("/{resource_id}/metrics", response_model=list[ResourceMetricResponse])
async def get_resource_metrics(
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    resource_q = _tenant_resource_query(tid).where(Resource.id == resource_id)
    resource = (await db.execute(resource_q)).scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    metrics = (
        await db.execute(
            select(ResourceMetric).where(ResourceMetric.resource_id == resource_id).order_by(ResourceMetric.collected_at.desc())
        )
    ).scalars().all()
    return metrics


@router.get("/{resource_id}/recommendations")
async def get_resource_recommendations(
    resource_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all optimization recommendations for a specific resource."""
    tid = _tenant_id(request)
    resource_q = _tenant_resource_query(tid).where(Resource.id == resource_id)
    resource = (await db.execute(resource_q)).scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    from src.models.recommendation import Recommendation
    recs = (
        await db.execute(
            select(Recommendation)
            .where(Recommendation.resource_id == resource_id)
            .order_by(Recommendation.estimated_savings.desc())
        )
    ).scalars().all()
    return [
        {
            "id": r.id,
            "type": r.type.value if hasattr(r.type, 'value') else str(r.type),
            "priority": r.priority.value if hasattr(r.priority, 'value') else str(r.priority),
            "status": r.status.value if hasattr(r.status, 'value') else str(r.status),
            "title": r.title,
            "description": r.description,
            "ai_explanation": r.ai_explanation,
            "current_monthly_cost": r.current_monthly_cost,
            "estimated_monthly_cost": r.estimated_monthly_cost,
            "estimated_savings": r.estimated_savings,
            "confidence_score": r.confidence_score,
            "recommended_config": r.recommended_config,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in recs
    ]


@router.get("/{resource_id}/metrics/history", response_model=ResourceMetricHistory)
async def get_resource_metrics_history(
    resource_id: int,
    request: Request,
    metric_name: str = Query(..., description="Metric name, e.g. cpu_utilization"),
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get historical time-series data for a specific metric on a resource."""
    tid = _tenant_id(request)
    resource_q = _tenant_resource_query(tid).where(Resource.id == resource_id)
    resource = (await db.execute(resource_q)).scalar_one_or_none()
    if not resource:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resource not found")

    from datetime import datetime, timedelta, timezone
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    metrics = (
        await db.execute(
            select(ResourceMetric)
            .where(
                ResourceMetric.resource_id == resource_id,
                ResourceMetric.metric_name == metric_name,
                ResourceMetric.collected_at >= cutoff,
            )
            .order_by(ResourceMetric.collected_at.asc())
        )
    ).scalars().all()

    datapoints = [
        ResourceMetricHistoryPoint(
            collected_at=m.collected_at,
            avg_value=m.avg_value,
            max_value=m.max_value,
            min_value=m.min_value,
            p95_value=m.p95_value,
        )
        for m in metrics
    ]

    return ResourceMetricHistory(
        metric_name=metric_name,
        period_days=days,
        datapoints=datapoints,
    )
