"""Architecture advisor endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.engine.architecture_advisor import ArchitectureAdvisor

router = APIRouter(prefix="/architecture", tags=["architecture"])


@router.get("/analyze")
async def analyze_architecture(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    advisor = ArchitectureAdvisor(db)
    return await advisor.analyze(user.tenant_id)
