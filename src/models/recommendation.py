import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, Float, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class RecommendationType(str, enum.Enum):
    RIGHTSIZE = "rightsize"
    TERMINATE = "terminate"
    RESERVE = "reserve"
    SPOT_CONVERT = "spot_convert"
    STORAGE_TIER = "storage_tier"
    DELETE_SNAPSHOT = "delete_snapshot"
    DELETE_VOLUME = "delete_volume"
    RELEASE_IP = "release_ip"
    MODERNIZE = "modernize"
    ARM_MIGRATE = "arm_migrate"
    SERVERLESS = "serverless"
    REGION_MOVE = "region_move"
    SAVINGS_PLAN = "savings_plan"
    GP3_UPGRADE = "gp3_upgrade"


class RecommendationPriority(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RecommendationStatus(str, enum.Enum):
    OPEN = "open"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    APPLIED = "applied"
    FAILED = "failed"


class Recommendation(Base):
    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    type: Mapped[RecommendationType] = mapped_column(Enum(RecommendationType), nullable=False)
    priority: Mapped[RecommendationPriority] = mapped_column(
        Enum(RecommendationPriority), default=RecommendationPriority.MEDIUM
    )
    status: Mapped[RecommendationStatus] = mapped_column(
        Enum(RecommendationStatus), default=RecommendationStatus.OPEN
    )

    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    ai_explanation: Mapped[str | None] = mapped_column(Text, nullable=True)

    current_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    current_monthly_cost: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_monthly_cost: Mapped[float] = mapped_column(Float, default=0.0)
    estimated_savings: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    jira_ticket_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    jira_ticket_url: Mapped[str | None] = mapped_column(String(512), nullable=True)

    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    resource: Mapped["Resource"] = relationship(back_populates="recommendations")
    actions: Mapped[list["RecommendationAction"]] = relationship(
        back_populates="recommendation", cascade="all, delete-orphan"
    )



class RecommendationAction(Base):
    __tablename__ = "recommendation_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    recommendation_id: Mapped[int] = mapped_column(
        ForeignKey("recommendations.id"), nullable=False, index=True
    )
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False)
    order: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    recommendation: Mapped["Recommendation"] = relationship(back_populates="actions")
