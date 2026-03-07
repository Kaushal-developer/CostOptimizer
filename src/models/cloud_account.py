import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, Text, JSON, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class CloudProvider(str, enum.Enum):
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class AccountStatus(str, enum.Enum):
    PENDING = "pending"
    CONNECTED = "connected"
    ERROR = "error"
    DISCONNECTED = "disconnected"


class CloudAccount(Base):
    __tablename__ = "cloud_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    provider: Mapped[CloudProvider] = mapped_column(Enum(CloudProvider), nullable=False)
    account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[AccountStatus] = mapped_column(Enum(AccountStatus), default=AccountStatus.PENDING)
    is_remediation_enabled: Mapped[bool] = mapped_column(Boolean, default=False)

    # AWS-specific
    aws_role_arn: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aws_access_key_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    aws_secret_access_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    aws_region: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Azure-specific
    azure_subscription_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    azure_tenant_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # GCP-specific
    gcp_project_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gcp_credentials_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    tenant: Mapped["Tenant"] = relationship(back_populates="cloud_accounts")
    resources: Mapped[list["Resource"]] = relationship(back_populates="cloud_account", cascade="all, delete-orphan")
