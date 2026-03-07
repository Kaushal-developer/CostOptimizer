"""Budget monitoring service with threshold alerts."""

from __future__ import annotations

from datetime import datetime, timezone
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.budget import Budget, BudgetAlert, BudgetStatus
from src.api.websocket_manager import ws_manager


class BudgetService:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def check_budgets(self, tenant_id: int) -> list[dict]:
        """Check all budgets and trigger alerts for threshold breaches."""
        result = await self._db.execute(
            select(Budget).where(Budget.tenant_id == tenant_id)
        )
        budgets = result.scalars().all()
        alerts_triggered = []

        for budget in budgets:
            if budget.amount <= 0:
                continue

            utilization_pct = (budget.actual_spend / budget.amount) * 100

            new_status = BudgetStatus.ON_TRACK
            if utilization_pct >= budget.critical_threshold:
                new_status = BudgetStatus.OVER_BUDGET
            elif utilization_pct >= budget.warning_threshold:
                new_status = BudgetStatus.WARNING

            if new_status != budget.status:
                budget.status = new_status

                if new_status in (BudgetStatus.WARNING, BudgetStatus.OVER_BUDGET):
                    alert = BudgetAlert(
                        budget_id=budget.id,
                        tenant_id=tenant_id,
                        threshold_percentage=budget.warning_threshold if new_status == BudgetStatus.WARNING else budget.critical_threshold,
                        actual_percentage=round(utilization_pct, 1),
                        message=f"Budget '{budget.name}' is at {utilization_pct:.1f}% ({new_status.value})",
                    )
                    self._db.add(alert)

                    alert_data = {
                        "type": "budget_alert",
                        "budget_name": budget.name,
                        "status": new_status.value,
                        "utilization_pct": round(utilization_pct, 1),
                        "amount": budget.amount,
                        "actual_spend": budget.actual_spend,
                    }
                    await ws_manager.broadcast_to_channel(tenant_id, "budgets", alert_data)
                    alerts_triggered.append(alert_data)

        return alerts_triggered
