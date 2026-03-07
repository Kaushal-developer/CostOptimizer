"""Settings & Integration config CRUD."""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User
from src.models.integration_config import IntegrationConfig, IntegrationType

router = APIRouter(prefix="/settings", tags=["settings"])


class IntegrationCreate(BaseModel):
    type: IntegrationType
    name: str
    is_enabled: bool = True
    config: dict = {}


class IntegrationUpdate(BaseModel):
    name: str | None = None
    is_enabled: bool | None = None
    config: dict | None = None


class IntegrationResponse(BaseModel):
    id: int
    type: str
    name: str
    is_enabled: bool
    config: dict
    created_at: str
    model_config = {"from_attributes": True}


@router.get("/integrations")
async def list_integrations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IntegrationConfig).where(IntegrationConfig.tenant_id == user.tenant_id)
    )
    items = result.scalars().all()
    return [
        {
            "id": i.id, "type": i.type.value, "name": i.name,
            "is_enabled": i.is_enabled, "config": i.config,
            "created_at": i.created_at.isoformat(),
        }
        for i in items
    ]


@router.post("/integrations", status_code=201)
async def create_integration(
    body: IntegrationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = IntegrationConfig(
        tenant_id=user.tenant_id,
        type=body.type,
        name=body.name,
        is_enabled=body.is_enabled,
        config=body.config,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return {"id": item.id, "type": item.type.value, "name": item.name, "is_enabled": item.is_enabled}


@router.put("/integrations/{integration_id}")
async def update_integration(
    integration_id: int,
    body: IntegrationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IntegrationConfig).where(
            IntegrationConfig.id == integration_id,
            IntegrationConfig.tenant_id == user.tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Integration not found")
    if body.name is not None:
        item.name = body.name
    if body.is_enabled is not None:
        item.is_enabled = body.is_enabled
    if body.config is not None:
        item.config = body.config
    return {"id": item.id, "type": item.type.value, "name": item.name, "is_enabled": item.is_enabled}


@router.delete("/integrations/{integration_id}", status_code=204)
async def delete_integration(
    integration_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(IntegrationConfig).where(
            IntegrationConfig.id == integration_id,
            IntegrationConfig.tenant_id == user.tenant_id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Integration not found")
    await db.delete(item)
