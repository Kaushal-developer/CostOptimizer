"""Compliance scan, findings, and scores endpoints."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.engine.compliance_engine import ComplianceEngine

router = APIRouter(prefix="/compliance", tags=["compliance"])


@router.get("/frameworks")
async def list_frameworks(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = ComplianceEngine(db)
    return await engine.initialize_frameworks(user.tenant_id)


@router.post("/scan")
async def run_scan(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = ComplianceEngine(db)
    result = await engine.run_scan(user.tenant_id)
    # Also return findings so frontend can display immediately
    findings = await engine.get_findings(user.tenant_id)
    result["findings"] = findings
    return result


@router.get("/findings")
async def get_findings(
    framework_id: int | None = None,
    severity: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    engine = ComplianceEngine(db)
    return await engine.get_findings(user.tenant_id, framework_id=framework_id, severity=severity)
