import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, JSON, Text, Float
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


class AlertSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class AlertStatus(str, enum.Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SUPPRESSED = "suppressed"


class AlertCategory(str, enum.Enum):
    OPEN_SECURITY_GROUP = "open_security_group"
    PUBLIC_S3 = "public_s3"
    UNENCRYPTED_VOLUME = "unencrypted_volume"
    IAM_ISSUE = "iam_issue"
    EXPOSED_CREDENTIALS = "exposed_credentials"
    NETWORK_EXPOSURE = "network_exposure"
    MISCONFIGURATION = "misconfiguration"
    ANOMALOUS_ACTIVITY = "anomalous_activity"


class SecurityAlert(Base):
    __tablename__ = "security_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    cloud_account_id: Mapped[int | None] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True, index=True)
    category: Mapped[AlertCategory] = mapped_column(Enum(AlertCategory), nullable=False)
    severity: Mapped[AlertSeverity] = mapped_column(Enum(AlertSeverity), nullable=False)
    status: Mapped[AlertStatus] = mapped_column(Enum(AlertStatus), default=AlertStatus.OPEN)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(512), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_score: Mapped[float] = mapped_column(Float, default=0.0)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
