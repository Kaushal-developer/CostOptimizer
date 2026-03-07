from fastapi import APIRouter, Depends, HTTPException, status, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.database import get_db
from src.core.security import get_current_user
from src.models.tenant import User, Tenant
from src.models.cloud_account import CloudAccount
from src.schemas.cloud_account import (
    CloudAccountCreate,
    CloudAccountUpdate,
    CloudAccountResponse,
    CloudAccountList,
)

router = APIRouter(prefix="/cloud-accounts", tags=["cloud-accounts"])


def _tenant_id(request: Request) -> int:
    return request.state.tenant_id


@router.get("", response_model=CloudAccountList)
async def list_cloud_accounts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    count_q = select(func.count()).select_from(CloudAccount).where(CloudAccount.tenant_id == tid)
    total = (await db.execute(count_q)).scalar() or 0

    q = (
        select(CloudAccount)
        .where(CloudAccount.tenant_id == tid)
        .order_by(CloudAccount.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    items = (await db.execute(q)).scalars().all()
    return CloudAccountList(items=items, total=total, page=page, page_size=page_size)


@router.get("/{account_id}", response_model=CloudAccountResponse)
async def get_cloud_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    tid = _tenant_id(request)
    result = await db.execute(
        select(CloudAccount).where(CloudAccount.id == account_id, CloudAccount.tenant_id == tid)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cloud account not found")
    return account


@router.post("", response_model=CloudAccountResponse, status_code=status.HTTP_201_CREATED)
async def create_cloud_account(
    body: CloudAccountCreate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot create cloud accounts")

    tid = _tenant_id(request)

    # Check account limit
    tenant = (await db.execute(select(Tenant).where(Tenant.id == tid))).scalar_one()
    count = (await db.execute(
        select(func.count()).select_from(CloudAccount).where(CloudAccount.tenant_id == tid)
    )).scalar() or 0
    if count >= tenant.max_cloud_accounts:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Account limit reached ({tenant.max_cloud_accounts}). Upgrade your plan.",
        )

    account = CloudAccount(tenant_id=tid, **body.model_dump(exclude_none=True))
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


@router.patch("/{account_id}", response_model=CloudAccountResponse)
async def update_cloud_account(
    account_id: int,
    body: CloudAccountUpdate,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot update cloud accounts")

    tid = _tenant_id(request)
    result = await db.execute(
        select(CloudAccount).where(CloudAccount.id == account_id, CloudAccount.tenant_id == tid)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cloud account not found")

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(account, field, value)
    await db.flush()
    await db.refresh(account)
    return account


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_cloud_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only owners and admins can delete accounts")

    tid = _tenant_id(request)
    result = await db.execute(
        select(CloudAccount).where(CloudAccount.id == account_id, CloudAccount.tenant_id == tid)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cloud account not found")

    await db.delete(account)


@router.post("/{account_id}/sync", status_code=status.HTTP_202_ACCEPTED)
async def sync_cloud_account(
    account_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if current_user.role.value == "viewer":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Viewers cannot trigger syncs")

    tid = _tenant_id(request)
    result = await db.execute(
        select(CloudAccount).where(CloudAccount.id == account_id, CloudAccount.tenant_id == tid)
    )
    account = result.scalar_one_or_none()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cloud account not found")

    # Run sync inline (in production this would be a Celery task)
    from src.services.sync_service import run_sync
    result = await run_sync(account, db)
    await db.commit()
    return {"message": "Sync complete", "account_id": account.id, **result}
