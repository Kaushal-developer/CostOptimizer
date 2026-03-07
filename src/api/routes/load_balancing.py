"""Load balancing analysis endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.engine.load_balancer_analyzer import LoadBalancerAnalyzer

router = APIRouter(prefix="/load-balancing", tags=["load-balancing"])


@router.get("/analysis")
async def analyze_distribution(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analyzer = LoadBalancerAnalyzer(db)
    return await analyzer.analyze_distribution(user.tenant_id)
