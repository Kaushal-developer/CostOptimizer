"""JIRA ticket management routes."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.recommendation import Recommendation
from src.services.jira_service import JiraService

router = APIRouter(prefix="/jira", tags=["jira"])

# Singleton mock service - in production, configure from integration_configs
_jira_service = JiraService()


class TicketCreate(BaseModel):
    recommendation_id: int
    summary: str | None = None
    description: str | None = None
    priority: str = "Medium"
    labels: list[str] = ["cost-optimization"]


@router.post("/tickets")
async def create_ticket(
    body: TicketCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Recommendation).where(
            Recommendation.id == body.recommendation_id,
            Recommendation.tenant_id == user.tenant_id,
        )
    )
    rec = result.scalar_one_or_none()
    if not rec:
        raise HTTPException(status_code=404, detail="Recommendation not found")

    summary = body.summary or f"[Cost Optimization] {rec.title}"
    description = body.description or (
        f"{rec.description}\n\n"
        f"Current Cost: ${rec.current_monthly_cost:.2f}/mo\n"
        f"Estimated Cost: ${rec.estimated_monthly_cost:.2f}/mo\n"
        f"Savings: ${rec.estimated_savings:.2f}/mo\n"
        f"Priority: {rec.priority.value}\n"
        f"Confidence: {rec.confidence_score:.0%}"
    )

    ticket = await _jira_service.create_ticket(
        summary=summary,
        description=description,
        priority=body.priority,
        labels=body.labels,
        recommendation_id=rec.id,
    )

    rec.jira_ticket_key = ticket["key"]
    rec.jira_ticket_url = ticket["url"]

    return {"ticket": ticket, "mock": _jira_service.is_mock}


@router.get("/tickets/{recommendation_id}")
async def get_tickets(
    recommendation_id: int,
    user: User = Depends(get_current_user),
):
    tickets = await _jira_service.get_tickets_for_recommendation(recommendation_id)
    return {"tickets": tickets, "mock": _jira_service.is_mock}
