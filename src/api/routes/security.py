"""Security alerts and threat detection endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.engine.threat_detector import ThreatDetector

router = APIRouter(prefix="/security", tags=["security"])


class AlertStatusUpdate(BaseModel):
    status: str


@router.post("/scan")
async def run_threat_scan(
    cloud_account_id: int | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detector = ThreatDetector(db)
    return await detector.run_scan(user.tenant_id, cloud_account_id)


@router.get("/alerts")
async def list_alerts(
    status: str | None = None,
    severity: str | None = None,
    limit: int = Query(100, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detector = ThreatDetector(db)
    return await detector.get_alerts(user.tenant_id, status=status, severity=severity, limit=limit)


@router.put("/alerts/{alert_id}/status")
async def update_alert_status(
    alert_id: int,
    body: AlertStatusUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detector = ThreatDetector(db)
    result = await detector.update_alert_status(alert_id, user.tenant_id, body.status)
    if not result:
        raise HTTPException(status_code=404, detail="Alert not found")
    return result


@router.get("/summary")
async def security_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    detector = ThreatDetector(db)
    return await detector.get_summary(user.tenant_id)
