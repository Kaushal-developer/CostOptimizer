"""Reservation advisor endpoints."""

from fastapi import APIRouter, Depends, Query
from src.core.security import get_current_user
from src.models.tenant import User
from src.engine.reservation_advisor import ReservationAdvisor

router = APIRouter(prefix="/reservations", tags=["reservations"])
advisor = ReservationAdvisor()


@router.get("/analyze")
async def analyze_reservations(
    monthly_cost: float = Query(..., description="Current monthly on-demand cost"),
    commitment_pct: float = Query(100, description="Percentage of usage to commit"),
    user: User = Depends(get_current_user),
):
    return advisor.analyze(monthly_cost, commitment_pct=commitment_pct)
