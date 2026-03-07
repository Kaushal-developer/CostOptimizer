from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, DateTime, Float, JSON
from sqlalchemy.orm import Mapped, mapped_column
from src.core.database import Base


class SavingsReport(Base):
    __tablename__ = "savings_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    cloud_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("cloud_accounts.id"), nullable=True
    )
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    total_spend: Mapped[float] = mapped_column(Float, default=0.0)
    potential_savings: Mapped[float] = mapped_column(Float, default=0.0)
    realized_savings: Mapped[float] = mapped_column(Float, default=0.0)
    optimization_score: Mapped[float] = mapped_column(Float, default=0.0)

    breakdown_by_category: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    breakdown_by_service: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    top_recommendations: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    executive_summary: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
