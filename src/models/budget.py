import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, Float, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class BudgetPeriod(str, enum.Enum):
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"


class BudgetStatus(str, enum.Enum):
    ON_TRACK = "on_track"
    WARNING = "warning"
    OVER_BUDGET = "over_budget"


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    period: Mapped[BudgetPeriod] = mapped_column(Enum(BudgetPeriod), default=BudgetPeriod.MONTHLY)
    status: Mapped[BudgetStatus] = mapped_column(Enum(BudgetStatus), default=BudgetStatus.ON_TRACK)
    actual_spend: Mapped[float] = mapped_column(Float, default=0.0)
    forecasted_spend: Mapped[float] = mapped_column(Float, default=0.0)
    cloud_account_id: Mapped[int | None] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=True)
    filters: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    warning_threshold: Mapped[float] = mapped_column(Float, default=80.0)
    critical_threshold: Mapped[float] = mapped_column(Float, default=100.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    alerts: Mapped[list["BudgetAlert"]] = relationship(back_populates="budget", cascade="all, delete-orphan")


class BudgetAlert(Base):
    __tablename__ = "budget_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    budget_id: Mapped[int] = mapped_column(ForeignKey("budgets.id"), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    threshold_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    actual_percentage: Mapped[float] = mapped_column(Float, nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    budget: Mapped["Budget"] = relationship(back_populates="alerts")
