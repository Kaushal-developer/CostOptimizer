from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.recommendation import Recommendation, RecommendationStatus
from src.schemas.recommendation import (
    RecommendationResponse,
    RecommendationList,
    RecommendationActionRequest,
    WhatIfRequest,
    WhatIfResponse,
)

router = APIRouter(prefix="/recommendations", tags=["recommendations"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


@router.get("", response_model=RecommendationList)
async def list_recommendations(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    type: str | None = None,
    priority: str | None = None,
    rec_status: str | None = Query(None, alias="status"),
    cloud_account_id: int | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    base = select(Recommendation).where(Recommendation.tenant_id == tid)

    if type:
        base = base.where(Recommendation.type == type)
    if priority:
        base = base.where(Recommendation.priority == priority)
    if rec_status:
        base = base.where(Recommendation.status == rec_status)
    if cloud_account_id:
        from src.models.resource import Resource
        from src.models.cloud_account import CloudAccount
        base = base.join(Resource, Recommendation.resource_id == Resource.id).where(
            Resource.cloud_account_id == cloud_account_id
        )

    count_q = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    q = base.order_by(Recommendation.estimated_savings.desc()).offset((page - 1) * page_size).limit(page_size)
    items = (await db.execute(q)).scalars().all()
    return RecommendationList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{recommendation_id}", response_model=RecommendationResponse)
async def get_recommendation(
    recommendation_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    result = await db.execute(
        select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.tenant_id == tid)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
    return rec


@router.post("/{recommendation_id}/action", response_model=RecommendationResponse)
async def action_recommendation(
    recommendation_id: int,
    body: RecommendationActionRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot modify recommendations")

    tid = _tenant_id(request)
    result = await db.execute(
        select(Recommendation).where(Recommendation.id == recommendation_id, Recommendation.tenant_id == tid)
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")

    action_map = {
        "accept": RecommendationStatus.ACCEPTED,
        "reject": RecommendationStatus.REJECTED,
        "apply": RecommendationStatus.APPLIED,
    }
    rec.status = action_map[body.action]
    if body.action == "apply":
        rec.applied_at = datetime.now(timezone.utc)
        rec.applied_by = current_user.id

    await db.flush()
    await db.refresh(rec)
    return rec


@router.post("/what-if", response_model=WhatIfResponse)
async def what_if_analysis(
    body: WhatIfRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    result = await db.execute(
        select(Recommendation).where(
            Recommendation.id.in_(body.recommendation_ids),
            Recommendation.tenant_id == tid,
        )
    )
    recs = result.scalars().all()
    if not recs:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No matching recommendations found")

    total_current = sum(r.current_monthly_cost for r in recs)
    total_estimated = sum(r.estimated_monthly_cost for r in recs)
    total_savings = sum(r.estimated_savings for r in recs)
    pct = (total_savings / total_current * 100) if total_current > 0 else 0.0

    return WhatIfResponse(
        total_current_cost=total_current,
        total_estimated_cost=total_estimated,
        total_savings=total_savings,
        savings_percentage=round(pct, 2),
        recommendations=recs,
    )
