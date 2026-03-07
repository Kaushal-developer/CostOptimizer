import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, Float, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class ResourceType(str, enum.Enum):
    COMPUTE = "compute"
    DATABASE = "database"
    STORAGE = "storage"
    NETWORK = "network"
    KUBERNETES = "kubernetes"
    SNAPSHOT = "snapshot"
    VOLUME = "volume"
    LOAD_BALANCER = "load_balancer"
    IP_ADDRESS = "ip_address"


class ResourceStatus(str, enum.Enum):
    ACTIVE = "active"
    IDLE = "idle"
    OVERPROVISIONED = "overprovisioned"
    UNDERUTILIZED = "underutilized"
    ZOMBIE = "zombie"
    OPTIMIZED = "optimized"


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(
        ForeignKey("cloud_accounts.id"), nullable=False, index=True
    )
    resource_id: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    resource_type: Mapped[ResourceType] = mapped_column(Enum(ResourceType), nullable=False, index=True)
    provider_resource_type: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[ResourceStatus] = mapped_column(
        Enum(ResourceStatus), default=ResourceStatus.ACTIVE
    )

    # Normalized attributes
    name: Mapped[str | None] = mapped_column(String(512), nullable=True)
    instance_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    vcpus: Mapped[int | None] = mapped_column(Integer, nullable=True)
    memory_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    storage_gb: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Cost
    monthly_cost: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")

    # Tags & metadata
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)

    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    cloud_account: Mapped["CloudAccount"] = relationship(back_populates="resources")
    metrics: Mapped[list["ResourceMetric"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list["Recommendation"]] = relationship(
        back_populates="resource", cascade="all, delete-orphan"
    )



class ResourceMetric(Base):
    __tablename__ = "resource_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False, index=True)
    metric_name: Mapped[str] = mapped_column(String(100), nullable=False)
    avg_value: Mapped[float] = mapped_column(Float, nullable=False)
    max_value: Mapped[float] = mapped_column(Float, nullable=False)
    min_value: Mapped[float] = mapped_column(Float, nullable=False)
    p95_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    resource: Mapped["Resource"] = relationship(back_populates="metrics")
