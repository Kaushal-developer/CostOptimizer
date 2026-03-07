from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.cloud_account import CloudAccount
from src.models.resource import Resource
from src.models.recommendation import Recommendation
from src.models.savings import SavingsReport
from src.schemas.dashboard import (
    DashboardSummary,
    SavingsOverview,
    CostBreakdown,
    NLQueryRequest,
    NLQueryResponse,
)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


@router.get("/summary", response_model=DashboardSummary)
async def get_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)

    # Cloud accounts count
    total_accounts = (await db.execute(
        select(func.count()).select_from(CloudAccount).where(CloudAccount.tenant_id == tid)
    )).scalar() or 0

    # Resource stats via join
    resource_base = (
        select(Resource)
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
    )
    total_resources = (await db.execute(
        select(func.count()).select_from(resource_base.subquery())
    )).scalar() or 0

    total_spend = (await db.execute(
        select(func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
    )).scalar() or 0.0

    # Recommendation stats
    rec_base = select(Recommendation).where(Recommendation.tenant_id == tid, Recommendation.status == "open")
    open_recs = (await db.execute(select(func.count()).select_from(rec_base.subquery()))).scalar() or 0

    critical_base = rec_base.where(Recommendation.priority == "critical")
    critical_recs = (await db.execute(select(func.count()).select_from(critical_base.subquery()))).scalar() or 0

    total_potential = (await db.execute(
        select(func.coalesce(func.sum(Recommendation.estimated_savings), 0.0))
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
    )).scalar() or 0.0

    # Cost breakdown by provider
    provider_rows = (await db.execute(
        select(CloudAccount.provider, func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(Resource, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(CloudAccount.provider)
    )).all()
    by_provider = {str(row[0].value): float(row[1]) for row in provider_rows}

    # By resource type
    type_rows = (await db.execute(
        select(Resource.resource_type, func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.resource_type)
    )).all()
    by_type = {str(row[0].value): float(row[1]) for row in type_rows}

    # By region
    region_rows = (await db.execute(
        select(Resource.region, func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.region)
    )).all()
    by_region = {row[0]: float(row[1]) for row in region_rows}

    opt_score = max(0.0, 100.0 - (total_potential / total_spend * 100)) if total_spend > 0 else 100.0

    # Top savings
    top_q = (
        select(Recommendation)
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
        .order_by(Recommendation.estimated_savings.desc())
        .limit(5)
    )
    top_recs = (await db.execute(top_q)).scalars().all()
    top_savings = [
        {"id": r.id, "title": r.title, "estimated_savings": r.estimated_savings, "priority": r.priority.value}
        for r in top_recs
    ]

    return DashboardSummary(
        total_cloud_accounts=total_accounts,
        total_resources=total_resources,
        total_monthly_spend=float(total_spend),
        total_potential_savings=float(total_potential),
        open_recommendations=open_recs,
        critical_recommendations=critical_recs,
        optimization_score=round(opt_score, 1),
        cost_breakdown=CostBreakdown(by_provider=by_provider, by_resource_type=by_type, by_region=by_region),
        top_savings_opportunities=top_savings,
    )


@router.get("/savings", response_model=SavingsOverview)
async def get_savings_overview(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    result = await db.execute(
        select(SavingsReport)
        .where(SavingsReport.tenant_id == tid)
        .order_by(SavingsReport.period_end.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if not report:
        return SavingsOverview(
            total_spend=0.0, potential_savings=0.0, realized_savings=0.0, optimization_score=0.0
        )

    return SavingsOverview(
        total_spend=report.total_spend,
        potential_savings=report.potential_savings,
        realized_savings=report.realized_savings,
        optimization_score=report.optimization_score,
        savings_by_category=report.breakdown_by_category or {},
        savings_by_service=report.breakdown_by_service or {},
        period_start=report.period_start,
        period_end=report.period_end,
        executive_summary=report.executive_summary,
    )


@router.post("/query", response_model=NLQueryResponse)
async def natural_language_query(
    body: NLQueryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)

    # Gather context for the LLM
    total_spend = (await db.execute(
        select(func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
    )).scalar() or 0.0

    total_potential = (await db.execute(
        select(func.coalesce(func.sum(Recommendation.estimated_savings), 0.0))
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
    )).scalar() or 0.0

    rec_count = (await db.execute(
        select(func.count()).select_from(Recommendation)
        .where(Recommendation.tenant_id == tid, Recommendation.status == "open")
    )).scalar() or 0

    type_rows = (await db.execute(
        select(Resource.resource_type, func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.resource_type)
        .order_by(func.sum(Resource.monthly_cost).desc())
        .limit(5)
    )).all()
    top_services = [f"{row[0].value}: ${float(row[1]):.2f}/mo" for row in type_rows]

    region_rows = (await db.execute(
        select(Resource.region, func.coalesce(func.sum(Resource.monthly_cost), 0.0))
        .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid)
        .group_by(Resource.region)
        .order_by(func.sum(Resource.monthly_cost).desc())
        .limit(5)
    )).all()
    regions = [f"{row[0]}: ${float(row[1]):.2f}/mo" for row in region_rows]

    context = {
        "total_spend": float(total_spend),
        "potential_savings": float(total_potential),
        "recommendation_count": rec_count,
        "top_services": top_services,
        "regions": regions,
        "cost_changes": [],
    }

    from src.llm.explanation_generator import ExplanationGenerator
    llm = ExplanationGenerator()
    answer = await llm.answer_natural_language_query(body.query, context)

    return NLQueryResponse(
        query=body.query,
        answer=answer,
        data=context,
        visualization_hint=None,
    )


# ------------------------------------------------------------------
# Cost Explorer endpoints (uses cached data or live AWS calls)
# ------------------------------------------------------------------

async def _get_ce_service(db: AsyncSession, tid: int):
    """Build a CostExplorerService from the first connected cloud account."""
    account = (await db.execute(
        select(CloudAccount).where(
            CloudAccount.tenant_id == tid,
            CloudAccount.status == "connected",
            CloudAccount.provider == "aws",
        ).limit(1)
    )).scalar_one_or_none()
    if not account:
        return None, None

    creds = {}
    if account.aws_access_key_id:
        creds = {
            "aws_access_key_id": account.aws_access_key_id,
            "aws_secret_access_key": account.aws_secret_access_key,
        }
    else:
        return None, None

    from src.services.cost_explorer_service import CostExplorerService
    return CostExplorerService(creds), account


@router.get("/daily-costs")
async def get_daily_costs(
    request: Request,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)

    # Try cached data first
    from src.models.cost_data import DailyCost
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days)
    cached = (await db.execute(
        select(DailyCost)
        .join(CloudAccount, DailyCost.cloud_account_id == CloudAccount.id)
        .where(CloudAccount.tenant_id == tid, DailyCost.cost_date >= cutoff)
        .order_by(DailyCost.cost_date)
    )).scalars().all()

    if cached:
        return [
            {"date": str(c.cost_date), "service": c.service, "cost": c.cost}
            for c in cached
        ]

    # Fall back to live API call
    ce_svc, account = await _get_ce_service(db, tid)
    if not ce_svc:
        return []
    try:
        data = await ce_svc.get_daily_costs(days=days)
        # Cache it
        await ce_svc.cache_daily_costs(db, account.id, days=days)
        return data
    except Exception:
        return []


@router.get("/cost-by-service")
async def get_cost_by_service(
    request: Request,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        # Fall back to resource-based breakdown
        type_rows = (await db.execute(
            select(Resource.resource_type, func.sum(Resource.monthly_cost))
            .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
            .where(CloudAccount.tenant_id == tid)
            .group_by(Resource.resource_type)
            .order_by(func.sum(Resource.monthly_cost).desc())
        )).all()
        return {str(r[0].value): round(float(r[1]), 2) for r in type_rows}
    try:
        return await ce_svc.get_cost_by_service(days=days)
    except Exception:
        return {}


@router.get("/cost-by-region")
async def get_cost_by_region(
    request: Request,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        region_rows = (await db.execute(
            select(Resource.region, func.sum(Resource.monthly_cost))
            .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
            .where(CloudAccount.tenant_id == tid)
            .group_by(Resource.region)
            .order_by(func.sum(Resource.monthly_cost).desc())
        )).all()
        return {r[0]: round(float(r[1]), 2) for r in region_rows}
    try:
        return await ce_svc.get_cost_by_region(days=days)
    except Exception:
        return {}


@router.get("/monthly-trend")
async def get_monthly_trend(
    request: Request,
    months: int = 12,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        return []
    try:
        return await ce_svc.get_monthly_trend(months=months)
    except Exception:
        return []


@router.get("/cost-summary")
async def get_cost_summary_endpoint(
    request: Request,
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        total_spend = (await db.execute(
            select(func.coalesce(func.sum(Resource.monthly_cost), 0.0))
            .join(CloudAccount, Resource.cloud_account_id == CloudAccount.id)
            .where(CloudAccount.tenant_id == tid)
        )).scalar() or 0.0
        return {
            "current_period_cost": round(float(total_spend), 2),
            "previous_period_cost": 0,
            "change_percentage": 0,
            "period_days": days,
        }
    try:
        return await ce_svc.get_cost_summary(days=days)
    except Exception:
        return {"current_period_cost": 0, "previous_period_cost": 0, "change_percentage": 0, "period_days": days}


@router.get("/anomalies")
async def get_anomalies(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        return []
    try:
        return await ce_svc.get_cost_anomalies()
    except Exception:
        return []


@router.get("/forecast")
async def get_forecast(
    request: Request,
    months: int = 3,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    ce_svc, _ = await _get_ce_service(db, tid)
    if not ce_svc:
        return {"total_forecasted": 0, "periods": []}
    try:
        return await ce_svc.get_cost_forecast(months=months)
    except Exception:
        return {"total_forecasted": 0, "periods": []}


@router.get("/savings-plans")
async def get_savings_plans_summary(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    account = (await db.execute(
        select(CloudAccount).where(
            CloudAccount.tenant_id == tid,
            CloudAccount.status == "connected",
            CloudAccount.provider == "aws",
        ).limit(1)
    )).scalar_one_or_none()
    if not account or not account.aws_access_key_id:
        return {"plans": [], "coverage": {}, "utilization": {}, "purchase_recommendations": []}

    creds = {
        "aws_access_key_id": account.aws_access_key_id,
        "aws_secret_access_key": account.aws_secret_access_key,
    }
    from src.services.savings_plans_service import SavingsPlansService
    sp_svc = SavingsPlansService(creds)
    try:
        import asyncio
        plans, coverage, utilization, recs = await asyncio.gather(
            sp_svc.get_savings_plans(),
            sp_svc.get_coverage(),
            sp_svc.get_utilization(),
            sp_svc.get_purchase_recommendations(),
            return_exceptions=True,
        )
        return {
            "plans": plans if not isinstance(plans, Exception) else [],
            "coverage": coverage if not isinstance(coverage, Exception) else {},
            "utilization": utilization if not isinstance(utilization, Exception) else {},
            "purchase_recommendations": recs if not isinstance(recs, Exception) else [],
        }
    except Exception:
        return {"plans": [], "coverage": {}, "utilization": {}, "purchase_recommendations": []}
