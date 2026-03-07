"""Models for cost data, savings plans, billing, and chat."""

from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime, Float, JSON, Text, Date, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class DailyCost(Base):
    __tablename__ = "daily_costs"
    __table_args__ = (
        UniqueConstraint("cloud_account_id", "cost_date", "service", "region", name="uq_daily_cost"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    cost_date: Mapped[datetime] = mapped_column(Date, nullable=False, index=True)
    service: Mapped[str] = mapped_column(String(255), nullable=False, default="Total")
    region: Mapped[str] = mapped_column(String(100), nullable=False, default="global")
    cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    granularity: Mapped[str] = mapped_column(String(20), default="daily")  # daily, monthly
    metric_type: Mapped[str] = mapped_column(String(50), default="UnblendedCost")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CostAnomaly(Base):
    __tablename__ = "cost_anomalies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    anomaly_id: Mapped[str] = mapped_column(String(255), nullable=False)
    start_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    end_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    expected_spend: Mapped[float] = mapped_column(Float, default=0.0)
    actual_spend: Mapped[float] = mapped_column(Float, default=0.0)
    total_impact: Mapped[float] = mapped_column(Float, default=0.0)
    root_causes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="open")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class CostForecast(Base):
    __tablename__ = "cost_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    forecast_date: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_end: Mapped[datetime] = mapped_column(Date, nullable=False)
    mean_value: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[float] = mapped_column(Float, nullable=True)
    upper_bound: Mapped[float] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SavingsPlanRecord(Base):
    __tablename__ = "savings_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(String(255), nullable=False)
    plan_type: Mapped[str] = mapped_column(String(100), nullable=False)  # Compute, EC2Instance, SageMaker
    state: Mapped[str] = mapped_column(String(50), nullable=False)  # active, expired, queued
    commitment_per_hour: Mapped[float] = mapped_column(Float, default=0.0)
    payment_option: Mapped[str] = mapped_column(String(50), default="No Upfront")
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ReservedInstanceRecord(Base):
    __tablename__ = "reserved_instances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    ri_id: Mapped[str] = mapped_column(String(255), nullable=False)
    instance_type: Mapped[str] = mapped_column(String(100), nullable=False)
    instance_count: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(50), nullable=False)
    offering_type: Mapped[str] = mapped_column(String(100), default="No Upfront")
    fixed_price: Mapped[float] = mapped_column(Float, default=0.0)
    usage_price: Mapped[float] = mapped_column(Float, default=0.0)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scope: Mapped[str] = mapped_column(String(50), default="Region")
    product_description: Mapped[str] = mapped_column(String(255), default="Linux/UNIX")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class SavingsCoverage(Base):
    __tablename__ = "savings_coverage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    period_start: Mapped[datetime] = mapped_column(Date, nullable=False)
    period_end: Mapped[datetime] = mapped_column(Date, nullable=False)
    coverage_pct: Mapped[float] = mapped_column(Float, default=0.0)
    spend_covered: Mapped[float] = mapped_column(Float, default=0.0)
    on_demand_cost: Mapped[float] = mapped_column(Float, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class MonthlyBill(Base):
    __tablename__ = "monthly_bills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cloud_account_id: Mapped[int] = mapped_column(ForeignKey("cloud_accounts.id"), nullable=False, index=True)
    bill_month: Mapped[datetime] = mapped_column(Date, nullable=False)
    total: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    by_service: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    by_region: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # user, assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
