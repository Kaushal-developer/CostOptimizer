"""Comprehensive 22-check cost optimization agent.

Ported from awscostv2 CostOptimizationAgent patterns.
Each check analyzes resources and metrics to produce actionable findings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Instance family mappings for Graviton migration
GRAVITON_MAP: dict[str, str] = {
    "m5": "m6g", "m5a": "m6g", "m5n": "m6gd",
    "c5": "c7g", "c5a": "c7g", "c5n": "c7gn",
    "r5": "r6g", "r5a": "r6g", "r5n": "r6gd",
    "t3": "t4g", "t3a": "t4g",
    "m6i": "m7g", "c6i": "c7g", "r6i": "r7g",
}

OLD_GEN_PREFIXES = ["t2", "m4", "m3", "c4", "c3", "r4", "r3", "i3", "d2"]

SPOT_KEYWORDS = ["dev", "test", "staging", "batch", "ci", "qa", "sandbox", "demo", "temp"]

# Size-based rough monthly cost estimates
INSTANCE_COST_ESTIMATE: dict[str, float] = {
    "nano": 4, "micro": 8, "small": 16, "medium": 32, "large": 65,
    "xlarge": 130, "2xlarge": 260, "4xlarge": 520, "8xlarge": 1040,
    "12xlarge": 1560, "16xlarge": 2080, "24xlarge": 3120, "metal": 4000,
}


@dataclass
class Finding:
    check: str
    severity: str  # critical, high, medium, low, info
    title: str
    description: str
    resource_id: str | None = None
    resource_type: str | None = None
    estimated_monthly_savings: float = 0.0
    actions: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


def _estimate_monthly_cost(instance_type: str) -> float:
    """Rough monthly cost estimate based on instance size."""
    parts = instance_type.rsplit(".", 1)
    if len(parts) == 2:
        return INSTANCE_COST_ESTIMATE.get(parts[1], 65)
    return 65


class CostOptimizationAgent:
    """Runs 22 cost optimization checks across all resources."""

    def run_full_analysis(
        self,
        resources: list[dict],
        metrics: dict[str, list[dict]],  # {resource_id: [metric_dicts]}
    ) -> dict:
        """Run all checks and return structured report."""
        findings: list[Finding] = []

        checks = [
            self._check_idle_instances,
            self._check_rightsizing,
            self._check_old_gen_instances,
            self._check_graviton_migration,
            self._check_spot_opportunities,
            self._check_unattached_ebs,
            self._check_gp2_volumes,
            self._check_oversized_ebs,
            self._check_old_snapshots,
            self._check_unused_elastic_ips,
            self._check_idle_rds,
            self._check_rds_rightsizing,
            self._check_rds_multi_az_dev,
            self._check_idle_load_balancers,
            self._check_s3_lifecycle,
            self._check_s3_versioning,
            self._check_lambda_memory,
            self._check_tagging_compliance,
            self._check_ebs_encryption,
            self._check_rds_backup_retention,
            self._check_public_access,
            self._check_monitoring_disabled,
        ]

        for check_fn in checks:
            try:
                results = check_fn(resources, metrics)
                findings.extend(results)
            except Exception as e:
                logger.warning("check_failed", check=check_fn.__name__, error=str(e))

        total_savings = sum(f.estimated_monthly_savings for f in findings)
        severity_counts = {}
        for f in findings:
            severity_counts[f.severity] = severity_counts.get(f.severity, 0) + 1

        return {
            "total_findings": len(findings),
            "total_estimated_savings": round(total_savings, 2),
            "severity_distribution": severity_counts,
            "findings": [
                {
                    "check": f.check,
                    "severity": f.severity,
                    "title": f.title,
                    "description": f.description,
                    "resource_id": f.resource_id,
                    "resource_type": f.resource_type,
                    "estimated_monthly_savings": f.estimated_monthly_savings,
                    "actions": f.actions,
                }
                for f in sorted(findings, key=lambda x: -x.estimated_monthly_savings)
            ],
        }

    # ------------------------------------------------------------------
    # Compute checks (1-5)
    # ------------------------------------------------------------------

    def _check_idle_instances(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "compute":
                continue
            rm = metrics.get(str(r["id"]), [])
            cpu = next((m for m in rm if m["metric_name"] == "cpu_utilization"), None)
            if cpu and cpu["avg_value"] < 5:
                cost = r.get("monthly_cost", _estimate_monthly_cost(r.get("instance_type", "")))
                findings.append(Finding(
                    check="idle_instances", severity="critical",
                    title=f"Idle Instance: {r.get('name') or r['resource_id']}",
                    description=f"CPU utilization is {cpu['avg_value']:.1f}% avg. Instance appears idle.",
                    resource_id=r["resource_id"], resource_type="EC2",
                    estimated_monthly_savings=cost * 0.9,
                    actions=["Terminate if not needed", "Downsize to t3.nano/t4g.nano", "Convert to spot instance"],
                ))
        return findings

    def _check_rightsizing(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "compute":
                continue
            rm = metrics.get(str(r["id"]), [])
            cpu = next((m for m in rm if m["metric_name"] == "cpu_utilization"), None)
            if cpu and 5 <= cpu["avg_value"] < 20:
                cost = r.get("monthly_cost", _estimate_monthly_cost(r.get("instance_type", "")))
                findings.append(Finding(
                    check="rightsizing", severity="high",
                    title=f"Oversized: {r.get('name') or r['resource_id']}",
                    description=f"CPU avg {cpu['avg_value']:.1f}%. Consider downsizing {r.get('instance_type', '')}.",
                    resource_id=r["resource_id"], resource_type="EC2",
                    estimated_monthly_savings=cost * 0.4,
                    actions=["Downsize to next smaller instance", "Monitor for 1 week after change"],
                ))
        return findings

    def _check_old_gen_instances(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            itype = r.get("instance_type", "")
            if not itype:
                continue
            family = itype.split(".")[0] if "." in itype else ""
            if family in OLD_GEN_PREFIXES:
                cost = r.get("monthly_cost", _estimate_monthly_cost(itype))
                findings.append(Finding(
                    check="old_gen_instances", severity="medium",
                    title=f"Old Generation: {r.get('name') or r['resource_id']}",
                    description=f"Running {itype} (old generation). Modern instances offer better price/performance.",
                    resource_id=r["resource_id"], resource_type=r.get("resource_type", ""),
                    estimated_monthly_savings=cost * 0.2,
                    actions=[f"Migrate from {family} to current generation", "Test compatibility before migration"],
                ))
        return findings

    def _check_graviton_migration(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "compute":
                continue
            itype = r.get("instance_type", "")
            arch = (r.get("metadata") or {}).get("architecture", "x86_64")
            if arch in ("arm64", "aarch64"):
                continue
            family = itype.split(".")[0] if "." in itype else ""
            if family in GRAVITON_MAP:
                size = itype.split(".", 1)[1] if "." in itype else ""
                target = f"{GRAVITON_MAP[family]}.{size}"
                cost = r.get("monthly_cost", _estimate_monthly_cost(itype))
                findings.append(Finding(
                    check="graviton_migration", severity="medium",
                    title=f"Graviton Candidate: {r.get('name') or r['resource_id']}",
                    description=f"Migrate {itype} to {target} for ~20% savings.",
                    resource_id=r["resource_id"], resource_type="EC2",
                    estimated_monthly_savings=cost * 0.2,
                    actions=[f"Test workload on {target}", "Update AMI for ARM64", "Use mixed instance ASG for gradual migration"],
                ))
        return findings

    def _check_spot_opportunities(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "compute":
                continue
            purchase = (r.get("metadata") or {}).get("purchase_type", "on-demand")
            if purchase == "spot":
                continue
            name = (r.get("name") or "").lower()
            tags = r.get("tags") or {}
            env_tag = tags.get("Environment", tags.get("environment", tags.get("Env", ""))).lower()
            combined = f"{name} {env_tag}"
            if any(kw in combined for kw in SPOT_KEYWORDS):
                cost = r.get("monthly_cost", _estimate_monthly_cost(r.get("instance_type", "")))
                findings.append(Finding(
                    check="spot_opportunities", severity="medium",
                    title=f"Spot Candidate: {r.get('name') or r['resource_id']}",
                    description=f"Non-production workload detected. Spot instances offer up to 90% savings.",
                    resource_id=r["resource_id"], resource_type="EC2",
                    estimated_monthly_savings=cost * 0.7,
                    actions=["Convert to spot instances", "Use spot fleet with fallback to on-demand"],
                ))
        return findings

    # ------------------------------------------------------------------
    # Storage checks (6-9)
    # ------------------------------------------------------------------

    def _check_unattached_ebs(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "volume":
                continue
            md = r.get("metadata") or {}
            attachments = md.get("attachments", [])
            if not attachments or all(not a for a in attachments):
                cost = r.get("monthly_cost", 0)
                findings.append(Finding(
                    check="unattached_ebs", severity="high",
                    title=f"Unattached Volume: {r.get('name') or r['resource_id']}",
                    description=f"EBS volume is not attached to any instance. Costing ${cost:.2f}/mo.",
                    resource_id=r["resource_id"], resource_type="EBS",
                    estimated_monthly_savings=cost,
                    actions=["Delete if not needed", "Create snapshot before deletion"],
                ))
        return findings

    def _check_gp2_volumes(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "volume":
                continue
            md = r.get("metadata") or {}
            if md.get("volume_type") == "gp2":
                storage = r.get("storage_gb", 0)
                cost = r.get("monthly_cost", 0)
                savings = cost * 0.2  # gp3 is ~20% cheaper
                findings.append(Finding(
                    check="gp2_to_gp3", severity="medium",
                    title=f"GP2 Volume: {r.get('name') or r['resource_id']}",
                    description=f"Migrate {storage}GB gp2 to gp3 for better performance and lower cost.",
                    resource_id=r["resource_id"], resource_type="EBS",
                    estimated_monthly_savings=savings,
                    actions=["Migrate volume type from gp2 to gp3", "gp3 offers 20% lower cost + 3000 baseline IOPS"],
                ))
        return findings

    def _check_oversized_ebs(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "volume":
                continue
            rm = metrics.get(str(r["id"]), [])
            iops_metric = next((m for m in rm if "iops" in m["metric_name"].lower() or "ops" in m["metric_name"].lower()), None)
            if iops_metric and iops_metric["avg_value"] < 100:
                md = r.get("metadata") or {}
                provisioned_iops = md.get("iops", 0)
                if provisioned_iops and provisioned_iops > 3000:
                    findings.append(Finding(
                        check="oversized_ebs", severity="medium",
                        title=f"Oversized IOPS: {r.get('name') or r['resource_id']}",
                        description=f"Provisioned {provisioned_iops} IOPS but using only {iops_metric['avg_value']:.0f} avg.",
                        resource_id=r["resource_id"], resource_type="EBS",
                        estimated_monthly_savings=r.get("monthly_cost", 0) * 0.3,
                        actions=["Reduce provisioned IOPS", "Switch to gp3 with baseline 3000 IOPS"],
                    ))
        return findings

    def _check_old_snapshots(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        from datetime import datetime, timezone, timedelta
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        for r in resources:
            if r.get("resource_type") != "snapshot":
                continue
            md = r.get("metadata") or {}
            start_time = md.get("start_time", "")
            try:
                if start_time and datetime.fromisoformat(start_time.replace("Z", "+00:00")) < cutoff:
                    cost = r.get("monthly_cost", 0)
                    findings.append(Finding(
                        check="old_snapshots", severity="low",
                        title=f"Old Snapshot: {r.get('name') or r['resource_id']}",
                        description=f"Snapshot older than 90 days. Review if still needed.",
                        resource_id=r["resource_id"], resource_type="EBS Snapshot",
                        estimated_monthly_savings=cost,
                        actions=["Delete if no longer needed", "Implement lifecycle policy"],
                    ))
            except (ValueError, TypeError):
                pass
        return findings

    # ------------------------------------------------------------------
    # Network checks (10)
    # ------------------------------------------------------------------

    def _check_unused_elastic_ips(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "ip_address":
                continue
            md = r.get("metadata") or {}
            if not md.get("associated", True):
                findings.append(Finding(
                    check="unused_eips", severity="high",
                    title=f"Unused Elastic IP: {md.get('public_ip', r['resource_id'])}",
                    description="Unassociated Elastic IP incurs charges.",
                    resource_id=r["resource_id"], resource_type="Elastic IP",
                    estimated_monthly_savings=3.65,
                    actions=["Release if not needed", "Associate with an instance"],
                ))
        return findings

    # ------------------------------------------------------------------
    # Database checks (11-13)
    # ------------------------------------------------------------------

    def _check_idle_rds(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "database":
                continue
            rm = metrics.get(str(r["id"]), [])
            conn = next((m for m in rm if m["metric_name"] == "database_connections"), None)
            if conn and conn["avg_value"] < 1:
                cost = r.get("monthly_cost", 0)
                findings.append(Finding(
                    check="idle_rds", severity="critical",
                    title=f"Idle Database: {r.get('name') or r['resource_id']}",
                    description=f"Average connections: {conn['avg_value']:.1f}. Database appears unused.",
                    resource_id=r["resource_id"], resource_type="RDS",
                    estimated_monthly_savings=cost * 0.9,
                    actions=["Delete if not needed", "Take final snapshot before deletion", "Consider Aurora Serverless v2"],
                ))
        return findings

    def _check_rds_rightsizing(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "database":
                continue
            rm = metrics.get(str(r["id"]), [])
            cpu = next((m for m in rm if m["metric_name"] == "cpu_utilization"), None)
            if cpu and cpu["avg_value"] < 20:
                cost = r.get("monthly_cost", 0)
                findings.append(Finding(
                    check="rds_rightsizing", severity="high",
                    title=f"Oversized Database: {r.get('name') or r['resource_id']}",
                    description=f"CPU avg {cpu['avg_value']:.1f}%. Consider downsizing {r.get('instance_type', '')}.",
                    resource_id=r["resource_id"], resource_type="RDS",
                    estimated_monthly_savings=cost * 0.4,
                    actions=["Downsize instance class", "Consider Aurora Serverless v2 for variable workloads"],
                ))
        return findings

    def _check_rds_multi_az_dev(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "database":
                continue
            md = r.get("metadata") or {}
            if not md.get("multi_az"):
                continue
            name = (r.get("name") or "").lower()
            tags = r.get("tags") or {}
            env = tags.get("Environment", "").lower()
            if any(kw in f"{name} {env}" for kw in ["dev", "test", "staging"]):
                cost = r.get("monthly_cost", 0)
                findings.append(Finding(
                    check="rds_multi_az_dev", severity="medium",
                    title=f"Multi-AZ on Dev: {r.get('name') or r['resource_id']}",
                    description="Non-production database running with Multi-AZ (2x cost).",
                    resource_id=r["resource_id"], resource_type="RDS",
                    estimated_monthly_savings=cost * 0.5,
                    actions=["Disable Multi-AZ for dev/test databases"],
                ))
        return findings

    # ------------------------------------------------------------------
    # Load Balancer checks (14)
    # ------------------------------------------------------------------

    def _check_idle_load_balancers(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "load_balancer":
                continue
            rm = metrics.get(str(r["id"]), [])
            req = next((m for m in rm if m["metric_name"] == "request_count"), None)
            if req and req["avg_value"] < 10:
                findings.append(Finding(
                    check="idle_elb", severity="high",
                    title=f"Idle Load Balancer: {r.get('name') or r['resource_id']}",
                    description=f"Average {req['avg_value']:.0f} requests. Consider removing.",
                    resource_id=r["resource_id"], resource_type="ELB",
                    estimated_monthly_savings=r.get("monthly_cost", 22),
                    actions=["Delete if no active targets", "Consolidate with other load balancers"],
                ))
        return findings

    # ------------------------------------------------------------------
    # S3 checks (15-16)
    # ------------------------------------------------------------------

    def _check_s3_lifecycle(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("provider_resource_type") != "s3:bucket":
                continue
            md = r.get("metadata") or {}
            if not md.get("lifecycle_rules_count"):
                rm = metrics.get(str(r["id"]), [])
                size = next((m for m in rm if m["metric_name"] == "bucket_size_bytes"), None)
                if size and size["avg_value"] > 1e9:  # > 1GB
                    findings.append(Finding(
                        check="s3_lifecycle", severity="medium",
                        title=f"No Lifecycle Policy: {r.get('name') or r['resource_id']}",
                        description="Large bucket without lifecycle rules. Consider tiering to S3 IA/Glacier.",
                        resource_id=r["resource_id"], resource_type="S3",
                        estimated_monthly_savings=size["avg_value"] / 1e9 * 0.01,
                        actions=["Add lifecycle rules for Intelligent-Tiering", "Move infrequent data to S3 IA/Glacier"],
                    ))
        return findings

    def _check_s3_versioning(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("provider_resource_type") != "s3:bucket":
                continue
            md = r.get("metadata") or {}
            if md.get("versioning") == "Enabled":
                rm = metrics.get(str(r["id"]), [])
                objs = next((m for m in rm if m["metric_name"] == "number_of_objects"), None)
                if objs and objs["avg_value"] > 100000:
                    findings.append(Finding(
                        check="s3_versioning", severity="low",
                        title=f"Versioning Overhead: {r.get('name') or r['resource_id']}",
                        description=f"Bucket has {objs['avg_value']:.0f} objects with versioning enabled. "
                                    "Old versions may accumulate costs.",
                        resource_id=r["resource_id"], resource_type="S3",
                        estimated_monthly_savings=0,
                        actions=["Add lifecycle rule to expire old versions", "Review if versioning is needed"],
                    ))
        return findings

    # ------------------------------------------------------------------
    # Governance checks (17-22)
    # ------------------------------------------------------------------

    def _check_lambda_memory(self, resources: list[dict], metrics: dict) -> list[Finding]:
        # No Lambda resources in current model, placeholder
        return []

    def _check_tagging_compliance(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        untagged = [r for r in resources if not r.get("tags") or len(r.get("tags", {})) == 0]
        if len(untagged) > 5:
            findings.append(Finding(
                check="tagging_compliance", severity="low",
                title=f"{len(untagged)} Resources Without Tags",
                description="Untagged resources make cost allocation difficult.",
                estimated_monthly_savings=0,
                actions=["Implement mandatory tagging policy", "Add Environment/Team/Project tags"],
            ))
        return findings

    def _check_ebs_encryption(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        unencrypted = [r for r in resources if r.get("resource_type") == "volume"
                       and not (r.get("metadata") or {}).get("encrypted")]
        if unencrypted:
            findings.append(Finding(
                check="ebs_encryption", severity="medium",
                title=f"{len(unencrypted)} Unencrypted EBS Volumes",
                description="Volumes without encryption pose a security risk.",
                estimated_monthly_savings=0,
                actions=["Enable default EBS encryption", "Migrate existing volumes to encrypted"],
            ))
        return findings

    def _check_rds_backup_retention(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "database":
                continue
            md = r.get("metadata") or {}
            retention = md.get("backup_retention_period", 7)
            if retention and retention > 14:
                cost = r.get("monthly_cost", 0)
                findings.append(Finding(
                    check="rds_backup_retention", severity="low",
                    title=f"High Backup Retention: {r.get('name') or r['resource_id']}",
                    description=f"Backup retention is {retention} days. Consider reducing if not required.",
                    resource_id=r["resource_id"], resource_type="RDS",
                    estimated_monthly_savings=cost * 0.05,
                    actions=[f"Reduce retention from {retention} to 7-14 days"],
                ))
        return findings

    def _check_public_access(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            md = r.get("metadata") or {}
            if md.get("publicly_accessible") or md.get("public_access_blocked") is False:
                findings.append(Finding(
                    check="public_access", severity="high",
                    title=f"Public Access: {r.get('name') or r['resource_id']}",
                    description="Resource is publicly accessible. Review if intentional.",
                    resource_id=r["resource_id"],
                    resource_type=r.get("resource_type", ""),
                    estimated_monthly_savings=0,
                    actions=["Disable public access if not needed", "Use VPC endpoints or private subnets"],
                ))
        return findings

    def _check_monitoring_disabled(self, resources: list[dict], metrics: dict) -> list[Finding]:
        findings = []
        for r in resources:
            if r.get("resource_type") != "compute":
                continue
            md = r.get("metadata") or {}
            if md.get("monitoring") == "disabled":
                findings.append(Finding(
                    check="monitoring_disabled", severity="low",
                    title=f"No Detailed Monitoring: {r.get('name') or r['resource_id']}",
                    description="Detailed monitoring disabled. 1-minute metrics help with rightsizing decisions.",
                    resource_id=r["resource_id"], resource_type="EC2",
                    estimated_monthly_savings=0,
                    actions=["Enable detailed monitoring ($3.50/instance/month)"],
                ))
        return findings
