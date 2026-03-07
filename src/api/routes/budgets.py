"""Budget management endpoints."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.budget import Budget, BudgetAlert, BudgetPeriod, BudgetStatus

router = APIRouter(prefix="/budgets", tags=["budgets"])


class BudgetCreate(BaseModel):
    name: str
    amount: float
    period: str = "monthly"
    cloud_account_id: int | None = None
    warning_threshold: float = 80.0
    critical_threshold: float = 100.0
    filters: dict | None = None


class BudgetUpdate(BaseModel):
    name: str | None = None
    amount: float | None = None
    warning_threshold: float | None = None
    critical_threshold: float | None = None


@router.get("")
async def list_budgets(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Budget).where(Budget.tenant_id == user.tenant_id).order_by(Budget.created_at.desc())
    )
    budgets = result.scalars().all()
    return [
        {
            "id": b.id, "name": b.name, "amount": b.amount,
            "period": b.period.value, "status": b.status.value,
            "actual_spend": b.actual_spend, "forecasted_spend": b.forecasted_spend,
            "warning_threshold": b.warning_threshold,
            "critical_threshold": b.critical_threshold,
            "utilization_pct": round((b.actual_spend / b.amount * 100) if b.amount > 0 else 0, 1),
            "cloud_account_id": b.cloud_account_id,
            "created_at": b.created_at.isoformat(),
        }
        for b in budgets
    ]


@router.post("", status_code=201)
async def create_budget(
    body: BudgetCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    budget = Budget(
        tenant_id=user.tenant_id,
        name=body.name,
        amount=body.amount,
        period=BudgetPeriod(body.period),
        cloud_account_id=body.cloud_account_id,
        warning_threshold=body.warning_threshold,
        critical_threshold=body.critical_threshold,
        filters=body.filters,
    )
    db.add(budget)
    await db.flush()
    await db.refresh(budget)
    return {"id": budget.id, "name": budget.name, "amount": budget.amount, "status": budget.status.value}


@router.put("/{budget_id}")
async def update_budget(
    budget_id: int,
    body: BudgetUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Budget).where(Budget.id == budget_id, Budget.tenant_id == user.tenant_id)
    )
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    if body.name is not None:
        budget.name = body.name
    if body.amount is not None:
        budget.amount = body.amount
    if body.warning_threshold is not None:
        budget.warning_threshold = body.warning_threshold
    if body.critical_threshold is not None:
        budget.critical_threshold = body.critical_threshold
    return {"id": budget.id, "name": budget.name, "amount": budget.amount}


@router.delete("/{budget_id}", status_code=204)
async def delete_budget(
    budget_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Budget).where(Budget.id == budget_id, Budget.tenant_id == user.tenant_id)
    )
    budget = result.scalar_one_or_none()
    if not budget:
        raise HTTPException(status_code=404, detail="Budget not found")
    await db.delete(budget)


@router.get("/{budget_id}/alerts")
async def budget_alerts(
    budget_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BudgetAlert).where(
            BudgetAlert.budget_id == budget_id,
            BudgetAlert.tenant_id == user.tenant_id,
        ).order_by(BudgetAlert.triggered_at.desc()).limit(50)
    )
    return [
        {
            "id": a.id, "threshold_percentage": a.threshold_percentage,
            "actual_percentage": a.actual_percentage, "message": a.message,
            "triggered_at": a.triggered_at.isoformat(),
        }
        for a in result.scalars().all()
    ]
