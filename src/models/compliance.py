import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, ForeignKey, Enum, DateTime, Float, JSON, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from src.core.database import Base


class ComplianceSeverity(str, enum.Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class ComplianceStatus(str, enum.Enum):
    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    NOT_APPLICABLE = "not_applicable"


class ComplianceFramework(Base):
    __tablename__ = "compliance_frameworks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    last_scan_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    rules: Mapped[list["ComplianceRule"]] = relationship(back_populates="framework", cascade="all, delete-orphan")
    findings: Mapped[list["ComplianceFinding"]] = relationship(back_populates="framework", cascade="all, delete-orphan")


class ComplianceRule(Base):
    __tablename__ = "compliance_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("compliance_frameworks.id"), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    severity: Mapped[ComplianceSeverity] = mapped_column(Enum(ComplianceSeverity), default=ComplianceSeverity.MEDIUM)
    category: Mapped[str] = mapped_column(String(100), nullable=False)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    framework: Mapped["ComplianceFramework"] = relationship(back_populates="rules")


class ComplianceFinding(Base):
    __tablename__ = "compliance_findings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    framework_id: Mapped[int] = mapped_column(ForeignKey("compliance_frameworks.id"), nullable=False, index=True)
    rule_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id"), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(512), nullable=True)
    status: Mapped[ComplianceStatus] = mapped_column(Enum(ComplianceStatus), nullable=False)
    severity: Mapped[ComplianceSeverity] = mapped_column(Enum(ComplianceSeverity), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    remediation: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    found_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    framework: Mapped["ComplianceFramework"] = relationship(back_populates="findings")
