"""Compliance engine that checks REAL AWS resource data from the database
and makes live AWS API calls for account-level checks."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict

import boto3
import structlog
from botocore.exceptions import ClientError, BotoCoreError
from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.compliance import (
    ComplianceFramework, ComplianceRule, ComplianceFinding,
    ComplianceSeverity, ComplianceStatus,
)
from src.models.resource import Resource
from src.models.cloud_account import CloudAccount

logger = structlog.get_logger(__name__)

# ── Framework + rule definitions ──────────────────────────────────────

FRAMEWORK_DEFINITIONS = [
    {"name": "CIS AWS Benchmark", "version": "1.5.0", "description": "Center for Internet Security AWS Foundations Benchmark"},
    {"name": "SOC 2", "version": "2017", "description": "Service Organization Control 2 - Trust Services Criteria"},
    {"name": "HIPAA", "version": "2013", "description": "Health Insurance Portability and Accountability Act"},
    {"name": "PCI-DSS", "version": "4.0", "description": "Payment Card Industry Data Security Standard"},
    {"name": "NIST 800-53", "version": "Rev 5", "description": "NIST Security and Privacy Controls"},
    {"name": "ISO 27001", "version": "2022", "description": "Information Security Management System"},
    {"name": "GDPR", "version": "2016/679", "description": "General Data Protection Regulation"},
]

# rule_id -> checker function name (mapped below)
RULE_DEFINITIONS = {
    "CIS AWS Benchmark": [
        {"rule_id": "CIS-1.4", "title": "Ensure MFA is enabled for root account", "severity": "critical", "category": "IAM", "check": "check_root_mfa"},
        {"rule_id": "CIS-1.10", "title": "Ensure MFA is enabled for IAM users with console access", "severity": "high", "category": "IAM", "check": "check_iam_mfa"},
        {"rule_id": "CIS-1.12", "title": "Ensure no IAM access keys older than 90 days", "severity": "high", "category": "IAM", "check": "check_old_access_keys"},
        {"rule_id": "CIS-2.1", "title": "Ensure CloudTrail is enabled in all regions", "severity": "high", "category": "Logging", "check": "check_cloudtrail"},
        {"rule_id": "CIS-3.1", "title": "Ensure VPC flow logging is enabled", "severity": "medium", "category": "Networking", "check": "check_vpc_flow_logs"},
        {"rule_id": "CIS-4.1", "title": "Ensure no security groups allow ingress 0.0.0.0/0 to port 22", "severity": "high", "category": "Networking", "check": "check_sg_ssh_open"},
        {"rule_id": "CIS-4.2", "title": "Ensure no security groups allow ingress 0.0.0.0/0 to port 3389", "severity": "high", "category": "Networking", "check": "check_sg_rdp_open"},
        {"rule_id": "CIS-4.3", "title": "Ensure default security group restricts all traffic", "severity": "medium", "category": "Networking", "check": "check_default_sg"},
        {"rule_id": "CIS-5.1", "title": "Ensure EBS volumes are encrypted", "severity": "high", "category": "Encryption", "check": "check_ebs_encryption"},
        {"rule_id": "CIS-5.4", "title": "Ensure S3 buckets have encryption enabled", "severity": "high", "category": "Encryption", "check": "check_s3_encryption"},
    ],
    "SOC 2": [
        {"rule_id": "SOC2-CC6.1", "title": "Logical access controls - no public RDS instances", "severity": "high", "category": "Access Control", "check": "check_rds_public"},
        {"rule_id": "SOC2-CC6.3", "title": "Monitoring enabled on EC2 instances", "severity": "medium", "category": "Monitoring", "check": "check_ec2_monitoring"},
        {"rule_id": "SOC2-CC6.6", "title": "S3 public access blocked", "severity": "high", "category": "Access Control", "check": "check_s3_public_access"},
        {"rule_id": "SOC2-CC7.2", "title": "RDS deletion protection enabled", "severity": "medium", "category": "Data Protection", "check": "check_rds_deletion_protection"},
    ],
    "HIPAA": [
        {"rule_id": "HIPAA-164.312a", "title": "EBS volumes encrypted at rest", "severity": "critical", "category": "Encryption", "check": "check_ebs_encryption"},
        {"rule_id": "HIPAA-164.312e", "title": "RDS encryption enabled", "severity": "critical", "category": "Encryption", "check": "check_rds_encryption"},
        {"rule_id": "HIPAA-164.312b", "title": "CloudTrail audit logging enabled", "severity": "high", "category": "Logging", "check": "check_cloudtrail"},
        {"rule_id": "HIPAA-164.308a", "title": "S3 versioning for data integrity", "severity": "high", "category": "Data Protection", "check": "check_s3_versioning"},
    ],
    "PCI-DSS": [
        {"rule_id": "PCI-1.3", "title": "No public access to databases", "severity": "critical", "category": "Network Security", "check": "check_rds_public"},
        {"rule_id": "PCI-3.4", "title": "Data encryption at rest (EBS)", "severity": "critical", "category": "Encryption", "check": "check_ebs_encryption"},
        {"rule_id": "PCI-3.5", "title": "Data encryption at rest (RDS)", "severity": "critical", "category": "Encryption", "check": "check_rds_encryption"},
        {"rule_id": "PCI-10.1", "title": "Audit trail logging via CloudTrail", "severity": "high", "category": "Logging", "check": "check_cloudtrail"},
    ],
    "NIST 800-53": [
        {"rule_id": "NIST-AC-2", "title": "IAM access keys rotated within 90 days", "severity": "high", "category": "Access Control", "check": "check_old_access_keys"},
        {"rule_id": "NIST-AU-2", "title": "Audit events via CloudTrail", "severity": "medium", "category": "Logging", "check": "check_cloudtrail"},
        {"rule_id": "NIST-SC-8", "title": "Encryption in transit and at rest", "severity": "high", "category": "Encryption", "check": "check_ebs_encryption"},
        {"rule_id": "NIST-SC-28", "title": "S3 data encryption", "severity": "high", "category": "Encryption", "check": "check_s3_encryption"},
    ],
    "ISO 27001": [
        {"rule_id": "ISO-A.9.2", "title": "IAM user access management", "severity": "high", "category": "Access Control", "check": "check_iam_mfa"},
        {"rule_id": "ISO-A.10.1", "title": "Cryptographic controls on storage", "severity": "high", "category": "Encryption", "check": "check_ebs_encryption"},
        {"rule_id": "ISO-A.12.4", "title": "Logging and monitoring enabled", "severity": "medium", "category": "Logging", "check": "check_ec2_monitoring"},
        {"rule_id": "ISO-A.13.1", "title": "Network security - no open SGs", "severity": "high", "category": "Networking", "check": "check_sg_ssh_open"},
    ],
    "GDPR": [
        {"rule_id": "GDPR-Art.25", "title": "Data protection by design - S3 public access blocked", "severity": "high", "category": "Data Protection", "check": "check_s3_public_access"},
        {"rule_id": "GDPR-Art.32", "title": "Encryption of personal data storage", "severity": "high", "category": "Encryption", "check": "check_s3_encryption"},
        {"rule_id": "GDPR-Art.30", "title": "S3 versioning for data recovery", "severity": "medium", "category": "Data Protection", "check": "check_s3_versioning"},
        {"rule_id": "GDPR-Art.33", "title": "Incident detection via CloudTrail", "severity": "critical", "category": "Incident Response", "check": "check_cloudtrail"},
    ],
}


class ComplianceEngine:
    def __init__(self, db: AsyncSession):
        self._db = db
        self._aws_checks_cache: dict[str, dict] = {}

    # ── Framework initialization ──────────────────────────────────────

    async def initialize_frameworks(self, tenant_id: int) -> list[dict]:
        existing = await self._db.execute(
            select(ComplianceFramework).where(ComplianceFramework.tenant_id == tenant_id)
        )
        existing_list = existing.scalars().all()
        if existing_list:
            return [{"id": f.id, "name": f.name, "version": f.version, "score": f.score,
                      "last_scan_at": f.last_scan_at.isoformat() if f.last_scan_at else None}
                    for f in existing_list]

        frameworks = []
        for fdef in FRAMEWORK_DEFINITIONS:
            fw = ComplianceFramework(
                tenant_id=tenant_id, name=fdef["name"],
                version=fdef["version"], description=fdef["description"],
            )
            self._db.add(fw)
            await self._db.flush()

            for rdef in RULE_DEFINITIONS.get(fdef["name"], []):
                rule = ComplianceRule(
                    framework_id=fw.id, rule_id=rdef["rule_id"],
                    title=rdef["title"],
                    severity=ComplianceSeverity(rdef["severity"]),
                    category=rdef["category"],
                    remediation=f"Review and remediate: {rdef['title']}",
                )
                self._db.add(rule)

            frameworks.append({"id": fw.id, "name": fw.name, "version": fw.version,
                              "score": 0.0, "last_scan_at": None})
        return frameworks

    # ── Main scan ─────────────────────────────────────────────────────

    async def run_scan(self, tenant_id: int) -> dict:
        """Run compliance scan using REAL resource data and live AWS API calls."""
        # Ensure frameworks exist
        fws = await self._db.execute(
            select(ComplianceFramework).where(
                ComplianceFramework.tenant_id == tenant_id,
                ComplianceFramework.is_enabled == True,
            )
        )
        frameworks = fws.scalars().all()
        if not frameworks:
            await self.initialize_frameworks(tenant_id)
            fws = await self._db.execute(
                select(ComplianceFramework).where(ComplianceFramework.tenant_id == tenant_id)
            )
            frameworks = fws.scalars().all()

        # Clear old findings for this tenant
        await self._db.execute(
            delete(ComplianceFinding).where(ComplianceFinding.tenant_id == tenant_id)
        )

        # Load all resources with metadata
        resources = await self._load_resources(tenant_id)

        # Get AWS credentials for live API checks
        aws_creds = await self._get_aws_credentials(tenant_id)

        # Run AWS account-level checks (CloudTrail, IAM, SGs, VPC flow logs)
        if aws_creds:
            await self._run_aws_account_checks(aws_creds)

        # Now evaluate each framework
        results = []
        total_findings = 0

        for fw in frameworks:
            rule_defs = RULE_DEFINITIONS.get(fw.name, [])
            pass_count = 0
            fail_count = 0

            for rdef in rule_defs:
                check_name = rdef.get("check", "")
                checker = getattr(self, check_name, None)
                if not checker:
                    continue

                findings = checker(resources, tenant_id, fw.id, rdef)

                if not findings:
                    # All passed
                    pass_count += 1
                    finding = ComplianceFinding(
                        framework_id=fw.id, rule_id=rdef["rule_id"],
                        tenant_id=tenant_id, status=ComplianceStatus.PASS,
                        severity=ComplianceSeverity(rdef["severity"]),
                        title=rdef["title"], description=f"✓ {rdef['title']} - All checks passed",
                    )
                    self._db.add(finding)
                else:
                    fail_count += 1
                    total_findings += len(findings)
                    for f in findings:
                        self._db.add(f)

            total = pass_count + fail_count
            fw.score = (pass_count / total * 100) if total > 0 else 100.0
            fw.last_scan_at = datetime.now(timezone.utc)

            results.append({
                "framework": fw.name, "score": round(fw.score, 1),
                "passed": pass_count, "failed": fail_count, "total_rules": total,
            })

        return {"frameworks": results, "total_findings": total_findings}

    # ── Data loading helpers ──────────────────────────────────────────

    async def _load_resources(self, tenant_id: int) -> list[dict]:
        result = await self._db.execute(
            select(Resource)
            .join(Resource.cloud_account)
            .where(CloudAccount.tenant_id == tenant_id)
        )
        resources = []
        for r in result.scalars().all():
            meta = r.metadata_ or {}
            resources.append({
                "id": r.id, "resource_id": r.resource_id,
                "resource_type": r.resource_type.value if hasattr(r.resource_type, 'value') else r.resource_type,
                "provider_type": r.provider_resource_type,
                "region": r.region, "name": r.name,
                "instance_type": r.instance_type,
                "metadata": meta, "tags": r.tags or {},
            })
        return resources

    async def _get_aws_credentials(self, tenant_id: int) -> dict | None:
        result = await self._db.execute(
            select(CloudAccount).where(
                CloudAccount.tenant_id == tenant_id,
                CloudAccount.aws_access_key_id.isnot(None),
            ).limit(1)
        )
        account = result.scalar_one_or_none()
        if not account:
            return None
        return {
            "aws_access_key_id": account.aws_access_key_id,
            "aws_secret_access_key": account.aws_secret_access_key,
            "region": account.aws_region or "us-east-1",
        }

    async def _run_aws_account_checks(self, creds: dict) -> None:
        """Run live AWS API calls for account-level compliance checks."""
        region = creds.get("region", "us-east-1")
        kw = {"aws_access_key_id": creds["aws_access_key_id"],
              "aws_secret_access_key": creds["aws_secret_access_key"],
              "region_name": region}

        checks = {
            "cloudtrail": self._check_cloudtrail_api,
            "iam_mfa": self._check_iam_mfa_api,
            "root_mfa": self._check_root_mfa_api,
            "old_access_keys": self._check_old_access_keys_api,
            "security_groups": self._check_security_groups_api,
            "default_sg": self._check_default_sg_api,
            "vpc_flow_logs": self._check_vpc_flow_logs_api,
        }

        async def _run(name, fn):
            try:
                result = await asyncio.to_thread(fn, kw)
                self._aws_checks_cache[name] = result
            except Exception as e:
                logger.warning("aws_check_failed", check=name, error=str(e))
                self._aws_checks_cache[name] = {"error": str(e)}

        await asyncio.gather(*[_run(n, f) for n, f in checks.items()])

    # ── Live AWS API check functions ──────────────────────────────────

    @staticmethod
    def _check_cloudtrail_api(kw: dict) -> dict:
        ct = boto3.client("cloudtrail", **kw)
        trails = ct.describe_trails().get("trailList", [])
        multi_region = [t for t in trails if t.get("IsMultiRegionTrail")]
        return {"trails": len(trails), "multi_region": len(multi_region),
                "trail_names": [t["Name"] for t in trails], "pass": len(multi_region) > 0}

    @staticmethod
    def _check_iam_mfa_api(kw: dict) -> dict:
        iam = boto3.client("iam", **{k: v for k, v in kw.items() if k != "region_name"})
        users = iam.list_users().get("Users", [])
        no_mfa = []
        for u in users:
            mfa = iam.list_mfa_devices(UserName=u["UserName"]).get("MFADevices", [])
            if not mfa:
                # Check if user has console access
                try:
                    iam.get_login_profile(UserName=u["UserName"])
                    no_mfa.append(u["UserName"])
                except ClientError:
                    pass  # No console access = ok
        return {"total_users": len(users), "console_users_without_mfa": no_mfa,
                "pass": len(no_mfa) == 0}

    @staticmethod
    def _check_root_mfa_api(kw: dict) -> dict:
        iam = boto3.client("iam", **{k: v for k, v in kw.items() if k != "region_name"})
        try:
            summary = iam.get_account_summary()["SummaryMap"]
            root_mfa = summary.get("AccountMFAEnabled", 0)
            return {"root_mfa_enabled": bool(root_mfa), "pass": bool(root_mfa)}
        except ClientError as e:
            return {"error": str(e), "pass": False}

    @staticmethod
    def _check_old_access_keys_api(kw: dict) -> dict:
        iam = boto3.client("iam", **{k: v for k, v in kw.items() if k != "region_name"})
        users = iam.list_users().get("Users", [])
        old_keys = []
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        for u in users:
            keys = iam.list_access_keys(UserName=u["UserName"]).get("AccessKeyMetadata", [])
            for k in keys:
                if k["Status"] == "Active" and k["CreateDate"].replace(tzinfo=timezone.utc) < cutoff:
                    old_keys.append({"user": u["UserName"], "key_id": k["AccessKeyId"],
                                    "created": k["CreateDate"].isoformat(),
                                    "age_days": (datetime.now(timezone.utc) - k["CreateDate"].replace(tzinfo=timezone.utc)).days})
        return {"old_keys": old_keys, "pass": len(old_keys) == 0}

    @staticmethod
    def _check_security_groups_api(kw: dict) -> dict:
        ec2 = boto3.client("ec2", **kw)
        sgs = ec2.describe_security_groups().get("SecurityGroups", [])
        open_ssh = []
        open_rdp = []
        for sg in sgs:
            for perm in sg.get("IpPermissions", []):
                from_port = perm.get("FromPort", 0)
                to_port = perm.get("ToPort", 0)
                for ip_range in perm.get("IpRanges", []):
                    cidr = ip_range.get("CidrIp", "")
                    if cidr == "0.0.0.0/0":
                        if from_port <= 22 <= to_port:
                            open_ssh.append({"sg_id": sg["GroupId"], "sg_name": sg.get("GroupName", ""), "vpc": sg.get("VpcId", "")})
                        if from_port <= 3389 <= to_port:
                            open_rdp.append({"sg_id": sg["GroupId"], "sg_name": sg.get("GroupName", ""), "vpc": sg.get("VpcId", "")})
        return {"open_ssh": open_ssh, "open_rdp": open_rdp,
                "pass_ssh": len(open_ssh) == 0, "pass_rdp": len(open_rdp) == 0}

    @staticmethod
    def _check_default_sg_api(kw: dict) -> dict:
        ec2 = boto3.client("ec2", **kw)
        sgs = ec2.describe_security_groups(Filters=[{"Name": "group-name", "Values": ["default"]}]).get("SecurityGroups", [])
        non_restricted = []
        for sg in sgs:
            if sg.get("IpPermissions") or sg.get("IpPermissionsEgress"):
                has_rules = False
                for perm in sg.get("IpPermissions", []):
                    if perm.get("IpRanges") or perm.get("Ipv6Ranges") or perm.get("UserIdGroupPairs"):
                        has_rules = True
                if has_rules:
                    non_restricted.append({"sg_id": sg["GroupId"], "vpc": sg.get("VpcId", "")})
        return {"non_restricted_default_sgs": non_restricted, "pass": len(non_restricted) == 0}

    @staticmethod
    def _check_vpc_flow_logs_api(kw: dict) -> dict:
        ec2 = boto3.client("ec2", **kw)
        vpcs = ec2.describe_vpcs().get("Vpcs", [])
        flow_logs = ec2.describe_flow_logs().get("FlowLogs", [])
        vpc_ids_with_logs = {fl["ResourceId"] for fl in flow_logs}
        vpcs_without = [{"vpc_id": v["VpcId"], "is_default": v.get("IsDefault", False)}
                        for v in vpcs if v["VpcId"] not in vpc_ids_with_logs]
        return {"total_vpcs": len(vpcs), "vpcs_without_flow_logs": vpcs_without,
                "pass": len(vpcs_without) == 0}

    # ── Resource-based compliance check functions ─────────────────────
    # Each returns a list of ComplianceFinding (failures) or empty list (pass)

    def check_cloudtrail(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("cloudtrail", {})
        if cached.get("error"):
            return [self._fail(framework_id, tenant_id, rdef, f"Could not check CloudTrail: {cached['error']}",
                               remediation="Ensure IAM permissions include cloudtrail:DescribeTrails")]
        if not cached.get("pass", True):
            return [self._fail(framework_id, tenant_id, rdef,
                               f"CloudTrail: {cached.get('trails', 0)} trails found but none are multi-region. "
                               f"Trails: {', '.join(cached.get('trail_names', []))}",
                               remediation="Create a multi-region trail: aws cloudtrail create-trail --name org-trail --is-multi-region-trail --s3-bucket-name <bucket>")]
        return []

    def check_root_mfa(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("root_mfa", {})
        if not cached.get("pass", True):
            return [self._fail(framework_id, tenant_id, rdef,
                               "Root account MFA is not enabled",
                               remediation="Enable MFA on root account: AWS Console → IAM → Security Credentials → Assign MFA device")]
        return []

    def check_iam_mfa(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("iam_mfa", {})
        no_mfa = cached.get("console_users_without_mfa", [])
        if no_mfa:
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(no_mfa)} IAM console users without MFA: {', '.join(no_mfa)}",
                               resource_id=", ".join(no_mfa),
                               remediation="Enable MFA for each user: aws iam enable-mfa-device --user-name <user> --serial-number <arn> --authentication-code1 <code1> --authentication-code2 <code2>")]
        return []

    def check_old_access_keys(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("old_access_keys", {})
        old = cached.get("old_keys", [])
        if old:
            details = "; ".join(f"{k['user']} ({k['age_days']}d old, {k['key_id']})" for k in old)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(old)} access keys older than 90 days: {details}",
                               resource_id=", ".join(k["key_id"] for k in old),
                               remediation="Rotate keys: aws iam create-access-key --user-name <user> && aws iam delete-access-key --user-name <user> --access-key-id <old-key>",
                               details={"old_keys": old})]
        return []

    def check_sg_ssh_open(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("security_groups", {})
        open_ssh = cached.get("open_ssh", [])
        if open_ssh:
            sgs = ", ".join(f"{s['sg_id']} ({s['sg_name']})" for s in open_ssh)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(open_ssh)} security groups allow SSH (port 22) from 0.0.0.0/0: {sgs}",
                               resource_id=", ".join(s["sg_id"] for s in open_ssh),
                               remediation="Restrict SSH to specific IPs: aws ec2 revoke-security-group-ingress --group-id <sg-id> --protocol tcp --port 22 --cidr 0.0.0.0/0",
                               details={"open_security_groups": open_ssh})]
        return []

    def check_sg_rdp_open(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("security_groups", {})
        open_rdp = cached.get("open_rdp", [])
        if open_rdp:
            sgs = ", ".join(f"{s['sg_id']} ({s['sg_name']})" for s in open_rdp)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(open_rdp)} security groups allow RDP (port 3389) from 0.0.0.0/0: {sgs}",
                               resource_id=", ".join(s["sg_id"] for s in open_rdp),
                               remediation="Restrict RDP to specific IPs or use AWS Systems Manager for access")]
        return []

    def check_default_sg(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("default_sg", {})
        bad = cached.get("non_restricted_default_sgs", [])
        if bad:
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(bad)} default security groups have active rules: {', '.join(s['sg_id'] for s in bad)}",
                               remediation="Remove all inbound/outbound rules from default security groups")]
        return []

    def check_vpc_flow_logs(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        cached = self._aws_checks_cache.get("vpc_flow_logs", {})
        bad = cached.get("vpcs_without_flow_logs", [])
        if bad:
            vpc_list = ", ".join(f"{v['vpc_id']}{' (default)' if v['is_default'] else ''}" for v in bad)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(bad)} VPCs without flow logs: {vpc_list}",
                               resource_id=", ".join(v["vpc_id"] for v in bad),
                               remediation="Enable flow logs: aws ec2 create-flow-logs --resource-type VPC --resource-ids <vpc-id> --traffic-type ALL --log-destination-type cloud-watch-logs")]
        return []

    def check_ebs_encryption(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        volumes = [r for r in resources if r["provider_type"] == "ebs:volume"]
        unencrypted = [r for r in volumes if not r["metadata"].get("encrypted", False)]
        if unencrypted:
            names = "; ".join(f"{r['resource_id']} ({r['metadata'].get('volume_type', '?')}, {r['region']})" for r in unencrypted)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(unencrypted)} of {len(volumes)} EBS volumes are NOT encrypted: {names}",
                               resource_id=", ".join(r["resource_id"] for r in unencrypted),
                               remediation="Enable EBS default encryption: aws ec2 enable-ebs-encryption-by-default. For existing volumes, create encrypted snapshots and restore.",
                               details={"unencrypted_volumes": [r["resource_id"] for r in unencrypted]})]
        return []

    def check_s3_encryption(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        buckets = [r for r in resources if r["provider_type"] == "s3:bucket"]
        no_enc = [r for r in buckets if not r["metadata"].get("encryption")]
        if no_enc:
            names = ", ".join(r["name"] or r["resource_id"] for r in no_enc)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(no_enc)} of {len(buckets)} S3 buckets have no encryption: {names}",
                               resource_id=", ".join(r["resource_id"] for r in no_enc),
                               remediation="Enable default encryption: aws s3api put-bucket-encryption --bucket <name> --server-side-encryption-configuration '{\"Rules\":[{\"ApplyServerSideEncryptionByDefault\":{\"SSEAlgorithm\":\"AES256\"}}]}'")]
        return []

    def check_s3_public_access(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        buckets = [r for r in resources if r["provider_type"] == "s3:bucket"]
        public = [r for r in buckets if not r["metadata"].get("public_access_blocked", True)]
        if public:
            names = ", ".join(r["name"] or r["resource_id"] for r in public)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(public)} S3 buckets do NOT have public access blocked: {names}",
                               resource_id=", ".join(r["resource_id"] for r in public),
                               remediation="Block public access: aws s3api put-public-access-block --bucket <name> --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true")]
        return []

    def check_s3_versioning(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        buckets = [r for r in resources if r["provider_type"] == "s3:bucket"]
        no_ver = [r for r in buckets if r["metadata"].get("versioning", "Disabled") != "Enabled"]
        if no_ver:
            names = ", ".join(r["name"] or r["resource_id"] for r in no_ver[:10])
            suffix = f" and {len(no_ver) - 10} more" if len(no_ver) > 10 else ""
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(no_ver)} of {len(buckets)} S3 buckets have versioning disabled: {names}{suffix}",
                               resource_id=", ".join(r["resource_id"] for r in no_ver[:5]),
                               remediation="Enable versioning: aws s3api put-bucket-versioning --bucket <name> --versioning-configuration Status=Enabled")]
        return []

    def check_rds_public(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        dbs = [r for r in resources if r["provider_type"] == "rds:instance"]
        public = [r for r in dbs if r["metadata"].get("publicly_accessible", False)]
        if public:
            names = ", ".join(r["name"] or r["resource_id"] for r in public)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(public)} RDS instances are publicly accessible: {names}",
                               resource_id=", ".join(r["resource_id"] for r in public),
                               remediation="Disable public access: aws rds modify-db-instance --db-instance-identifier <id> --no-publicly-accessible")]
        return []

    def check_rds_encryption(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        dbs = [r for r in resources if r["provider_type"] == "rds:instance"]
        unenc = [r for r in dbs if not r["metadata"].get("encrypted", False)]
        if unenc:
            names = ", ".join(r["name"] or r["resource_id"] for r in unenc)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(unenc)} RDS instances are NOT encrypted: {names}",
                               resource_id=", ".join(r["resource_id"] for r in unenc),
                               remediation="RDS encryption must be enabled at creation. Create encrypted snapshot → restore to new encrypted instance.")]
        return []

    def check_rds_deletion_protection(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        dbs = [r for r in resources if r["provider_type"] == "rds:instance"]
        no_prot = [r for r in dbs if not r["metadata"].get("deletion_protection", False)]
        if no_prot:
            names = ", ".join(r["name"] or r["resource_id"] for r in no_prot)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(no_prot)} RDS instances without deletion protection: {names}",
                               resource_id=", ".join(r["resource_id"] for r in no_prot),
                               remediation="Enable deletion protection: aws rds modify-db-instance --db-instance-identifier <id> --deletion-protection")]
        return []

    def check_ec2_monitoring(self, resources, tenant_id, framework_id, rdef) -> list[ComplianceFinding]:
        instances = [r for r in resources if r["provider_type"] == "ec2:instance"]
        no_mon = [r for r in instances if r["metadata"].get("monitoring", "disabled") == "disabled"]
        if no_mon:
            names = ", ".join(r["name"] or r["resource_id"] for r in no_mon)
            return [self._fail(framework_id, tenant_id, rdef,
                               f"{len(no_mon)} of {len(instances)} EC2 instances have detailed monitoring disabled: {names}",
                               resource_id=", ".join(r["resource_id"] for r in no_mon),
                               remediation="Enable detailed monitoring: aws ec2 monitor-instances --instance-ids <id>")]
        return []

    # ── Helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _fail(framework_id, tenant_id, rdef, description, remediation=None,
              resource_id=None, details=None) -> ComplianceFinding:
        return ComplianceFinding(
            framework_id=framework_id,
            rule_id=rdef["rule_id"],
            tenant_id=tenant_id,
            status=ComplianceStatus.FAIL,
            severity=ComplianceSeverity(rdef["severity"]),
            title=rdef["title"],
            description=description,
            remediation=remediation or rdef.get("remediation", f"Review and remediate: {rdef['title']}"),
            resource_id=resource_id,
            details=details,
        )

    async def get_findings(self, tenant_id: int, framework_id: int | None = None,
                           severity: str | None = None) -> list[dict]:
        query = select(ComplianceFinding).where(ComplianceFinding.tenant_id == tenant_id)
        if framework_id:
            query = query.where(ComplianceFinding.framework_id == framework_id)
        if severity:
            query = query.where(ComplianceFinding.severity == ComplianceSeverity(severity))
        query = query.order_by(ComplianceFinding.found_at.desc()).limit(500)

        result = await self._db.execute(query)
        return [
            {
                "id": f.id, "framework_id": f.framework_id,
                "rule_id": f.rule_id, "status": f.status.value,
                "severity": f.severity.value, "title": f.title,
                "description": f.description, "remediation": f.remediation,
                "resource_id": f.resource_id, "details": f.details,
                "found_at": f.found_at.isoformat(),
            }
            for f in result.scalars().all()
        ]
