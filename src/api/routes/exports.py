"""Export APIs for resources, recommendations, utilization, and cost reports."""

import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.cloud_account import CloudAccount
from src.models.resource import Resource, ResourceMetric
from src.models.recommendation import Recommendation

router = APIRouter(prefix="/exports", tags=["exports"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


def _csv_response(content: str, filename: str) -> StreamingResponse:
    return StreamingResponse(
        io.StringIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/resources")
async def export_resources(
    request: Request,
    format: str = Query("csv", regex="^(csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    q = (
        select(Resource)
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .order_by(Resource.monthly_cost.desc())
    )
    resources = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Name", "Resource ID", "Type", "Region", "Status",
        "Instance Type", "vCPUs", "Memory (GB)", "Storage (GB)",
        "Monthly Cost", "Currency", "Last Seen",
    ])
    for r in resources:
        writer.writerow([
            r.name or "", r.resource_id, r.resource_type.value if hasattr(r.resource_type, 'value') else str(r.resource_type),
            r.region, r.status.value if hasattr(r.status, 'value') else str(r.status),
            r.instance_type or "", r.vcpus or "", r.memory_gb or "", r.storage_gb or "",
            f"{r.monthly_cost:.2f}", r.currency, str(r.last_seen_at or ""),
        ])

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _csv_response(output.getvalue(), f"resources_{ts}.csv")


@router.get("/recommendations")
async def export_recommendations(
    request: Request,
    format: str = Query("csv", regex="^(csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    q = (
        select(Recommendation)
        .where(Recommendation.tenant_id == tid)
        .order_by(Recommendation.estimated_savings.desc())
    )
    recs = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Title", "Type", "Priority", "Status",
        "Current Monthly Cost", "Estimated Monthly Cost", "Estimated Savings",
        "Confidence Score", "Description", "Created At",
    ])
    for r in recs:
        writer.writerow([
            r.title,
            r.type.value if hasattr(r.type, 'value') else str(r.type),
            r.priority.value if hasattr(r.priority, 'value') else str(r.priority),
            r.status.value if hasattr(r.status, 'value') else str(r.status),
            f"{r.current_monthly_cost:.2f}", f"{r.estimated_monthly_cost:.2f}",
            f"{r.estimated_savings:.2f}", f"{r.confidence_score:.2f}",
            r.description or "", str(r.created_at or ""),
        ])

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _csv_response(output.getvalue(), f"recommendations_{ts}.csv")


@router.get("/utilization")
async def export_utilization(
    request: Request,
    format: str = Query("csv", regex="^(csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    q = (
        select(Resource, ResourceMetric)
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .outerjoin(ResourceMetric, ResourceMetric.resource_id == Resource.id)
        .where(CloudAccount.tenant_id == tid)
        .order_by(Resource.monthly_cost.desc())
    )
    rows = (await db.execute(q)).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Resource Name", "Resource ID", "Type", "Region",
        "Instance Type", "Monthly Cost",
        "Metric", "Average", "Max", "Min", "P95",
    ])
    for resource, metric in rows:
        writer.writerow([
            resource.name or "", resource.resource_id,
            resource.resource_type.value if hasattr(resource.resource_type, 'value') else str(resource.resource_type),
            resource.region, resource.instance_type or "",
            f"{resource.monthly_cost:.2f}",
            metric.metric_name if metric else "",
            f"{metric.avg_value:.2f}" if metric else "",
            f"{metric.max_value:.2f}" if metric else "",
            f"{metric.min_value:.2f}" if metric else "",
            f"{metric.p95_value:.2f}" if metric and metric.p95_value else "",
        ])

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _csv_response(output.getvalue(), f"utilization_{ts}.csv")


@router.get("/cost-report")
async def export_cost_report(
    request: Request,
    format: str = Query("csv", regex="^(csv)$"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)

    # Cost by resource type
    type_rows = (await db.execute(
        select(Resource.resource_type, func.sum(Resource.monthly_cost), func.count())
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.resource_type)
        .order_by(func.sum(Resource.monthly_cost).desc())
    )).all()

    # Cost by region
    region_rows = (await db.execute(
        select(Resource.region, func.sum(Resource.monthly_cost), func.count())
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.region)
        .order_by(func.sum(Resource.monthly_cost).desc())
    )).all()

    output = io.StringIO()
    writer = csv.writer(output)

    writer.writerow(["=== Cost by Resource Type ==="])
    writer.writerow(["Resource Type", "Total Monthly Cost", "Resource Count"])
    for row in type_rows:
        writer.writerow([
            row[0].value if hasattr(row[0], 'value') else str(row[0]),
            f"{float(row[1]):.2f}", row[2],
        ])

    writer.writerow([])
    writer.writerow(["=== Cost by Region ==="])
    writer.writerow(["Region", "Total Monthly Cost", "Resource Count"])
    for row in region_rows:
        writer.writerow([row[0], f"{float(row[1]):.2f}", row[2]])

    ts = datetime.now(timezone.utc).strftime("%Y%m%d")
    return _csv_response(output.getvalue(), f"cost_report_{ts}.csv")
