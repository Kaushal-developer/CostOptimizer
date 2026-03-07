"""Threat detection engine - scans for security misconfigurations."""

from __future__ import annotations

import random
from datetime import datetime, timezone
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.security_alert import SecurityAlert, AlertSeverity, AlertStatus, AlertCategory
from src.models.resource import Resource
from src.api.websocket_manager import ws_manager


# Simulated threat patterns for demo
THREAT_PATTERNS = [
    {
        "category": AlertCategory.OPEN_SECURITY_GROUP,
        "severity": AlertSeverity.HIGH,
        "title": "Security group allows unrestricted SSH access (0.0.0.0/0:22)",
        "description": "A security group allows inbound SSH access from any IP address, exposing instances to brute-force attacks.",
        "remediation": "Restrict SSH access to specific IP ranges or use AWS Systems Manager Session Manager for access.",
        "resource_type": "security_group",
    },
    {
        "category": AlertCategory.PUBLIC_S3,
        "severity": AlertSeverity.CRITICAL,
        "title": "S3 bucket has public read access enabled",
        "description": "An S3 bucket is configured with public read access, potentially exposing sensitive data.",
        "remediation": "Enable S3 Block Public Access at the account level. Review bucket policies and ACLs.",
        "resource_type": "s3_bucket",
    },
    {
        "category": AlertCategory.UNENCRYPTED_VOLUME,
        "severity": AlertSeverity.MEDIUM,
        "title": "EBS volume is not encrypted",
        "description": "An EBS volume is not encrypted at rest, violating data protection requirements.",
        "remediation": "Create an encrypted copy of the volume and replace the unencrypted one. Enable default EBS encryption.",
        "resource_type": "ebs_volume",
    },
    {
        "category": AlertCategory.IAM_ISSUE,
        "severity": AlertSeverity.HIGH,
        "title": "IAM user has inline policy with admin access",
        "description": "An IAM user has an inline policy granting AdministratorAccess, bypassing centralized policy management.",
        "remediation": "Remove inline policies. Use managed policies and IAM groups for access control.",
        "resource_type": "iam_user",
    },
    {
        "category": AlertCategory.NETWORK_EXPOSURE,
        "severity": AlertSeverity.HIGH,
        "title": "RDS instance is publicly accessible",
        "description": "A database instance is configured with public accessibility, exposing it to the internet.",
        "remediation": "Disable public accessibility. Use VPC endpoints or bastion hosts for database access.",
        "resource_type": "rds_instance",
    },
    {
        "category": AlertCategory.MISCONFIGURATION,
        "severity": AlertSeverity.MEDIUM,
        "title": "CloudTrail logging is disabled in region",
        "description": "CloudTrail logging is not enabled in one or more regions, creating audit gaps.",
        "remediation": "Enable CloudTrail in all regions with a multi-region trail. Enable log file validation.",
        "resource_type": "cloudtrail",
    },
    {
        "category": AlertCategory.EXPOSED_CREDENTIALS,
        "severity": AlertSeverity.CRITICAL,
        "title": "IAM access key older than 90 days",
        "description": "An IAM access key has not been rotated in over 90 days, increasing compromise risk.",
        "remediation": "Rotate the access key immediately. Implement automated key rotation policies.",
        "resource_type": "iam_access_key",
    },
    {
        "category": AlertCategory.MISCONFIGURATION,
        "severity": AlertSeverity.LOW,
        "title": "S3 bucket versioning is not enabled",
        "description": "S3 bucket versioning is disabled, preventing recovery from accidental deletions.",
        "remediation": "Enable versioning on the S3 bucket. Consider lifecycle policies for version management.",
        "resource_type": "s3_bucket",
    },
]


class ThreatDetector:
    def __init__(self, db: AsyncSession):
        self._db = db

    async def run_scan(self, tenant_id: int, cloud_account_id: int | None = None) -> dict:
        """Run threat detection scan. In production, would check actual AWS configurations."""
        # Simulate finding a subset of threats
        num_findings = random.randint(3, len(THREAT_PATTERNS))
        selected = random.sample(THREAT_PATTERNS, num_findings)
        regions = ["us-east-1", "us-west-2", "eu-west-1", "ap-southeast-1"]

        alerts_created = []
        for pattern in selected:
            risk_score = {"critical": 95, "high": 75, "medium": 50, "low": 25, "info": 10}.get(
                pattern["severity"].value, 50
            ) + random.uniform(-10, 10)

            alert = SecurityAlert(
                tenant_id=tenant_id,
                cloud_account_id=cloud_account_id,
                category=pattern["category"],
                severity=pattern["severity"],
                title=pattern["title"],
                description=pattern["description"],
                resource_type=pattern["resource_type"],
                region=random.choice(regions),
                remediation=pattern["remediation"],
                risk_score=min(100, max(0, risk_score)),
                resource_id=f"arn:aws:{pattern['resource_type']}:{random.choice(regions)}:123456789012:example-{random.randint(1000,9999)}",
            )
            self._db.add(alert)
            alerts_created.append({
                "category": pattern["category"].value,
                "severity": pattern["severity"].value,
                "title": pattern["title"],
                "risk_score": round(alert.risk_score, 1),
            })

        # Broadcast alerts via WebSocket
        await ws_manager.broadcast_to_channel(tenant_id, "alerts", {
            "type": "security_scan_complete",
            "new_alerts": len(alerts_created),
            "alerts": alerts_created[:3],
        })

        severity_counts = {}
        for a in alerts_created:
            severity_counts[a["severity"]] = severity_counts.get(a["severity"], 0) + 1

        return {
            "total_alerts": len(alerts_created),
            "severity_breakdown": severity_counts,
            "alerts": alerts_created,
        }

    async def get_alerts(
        self, tenant_id: int, status: str | None = None,
        severity: str | None = None, limit: int = 100,
    ) -> list[dict]:
        query = select(SecurityAlert).where(SecurityAlert.tenant_id == tenant_id)
        if status:
            query = query.where(SecurityAlert.status == AlertStatus(status))
        if severity:
            query = query.where(SecurityAlert.severity == AlertSeverity(severity))
        query = query.order_by(SecurityAlert.detected_at.desc()).limit(limit)

        result = await self._db.execute(query)
        return [
            {
                "id": a.id, "category": a.category.value, "severity": a.severity.value,
                "status": a.status.value, "title": a.title, "description": a.description,
                "resource_id": a.resource_id, "resource_type": a.resource_type,
                "region": a.region, "remediation": a.remediation,
                "risk_score": a.risk_score, "detected_at": a.detected_at.isoformat(),
            }
            for a in result.scalars().all()
        ]

    async def update_alert_status(self, alert_id: int, tenant_id: int, new_status: str) -> dict | None:
        result = await self._db.execute(
            select(SecurityAlert).where(SecurityAlert.id == alert_id, SecurityAlert.tenant_id == tenant_id)
        )
        alert = result.scalar_one_or_none()
        if not alert:
            return None
        alert.status = AlertStatus(new_status)
        if new_status == "resolved":
            alert.resolved_at = datetime.now(timezone.utc)
        return {"id": alert.id, "status": alert.status.value}

    async def get_summary(self, tenant_id: int) -> dict:
        """Get security alert summary."""
        result = await self._db.execute(
            select(
                SecurityAlert.severity,
                SecurityAlert.status,
                func.count(),
            ).where(SecurityAlert.tenant_id == tenant_id)
            .group_by(SecurityAlert.severity, SecurityAlert.status)
        )
        rows = result.all()

        by_severity = {}
        by_status = {}
        total = 0
        for severity, status, count in rows:
            by_severity[severity.value] = by_severity.get(severity.value, 0) + count
            by_status[status.value] = by_status.get(status.value, 0) + count
            total += count

        return {
            "total_alerts": total,
            "by_severity": by_severity,
            "by_status": by_status,
            "risk_score": min(100, sum(
                {"critical": 25, "high": 15, "medium": 8, "low": 3}.get(s, 0) * c
                for s, c in by_severity.items()
            )),
        }
