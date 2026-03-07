"""AWS resource collector supporting both IAM Role and Access Key auth."""

from __future__ import annotations

import asyncio
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Any

import boto3
import structlog
from botocore.exceptions import BotoCoreError, ClientError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.ingestion.aws.pricing import AWSPricingHelper
from src.ingestion.base import BaseCollector, CollectedMetric, CollectedResource

logger = structlog.get_logger(__name__)

DEFAULT_REGIONS = [
    "us-east-1",
    "us-east-2",
    "us-west-1",
    "us-west-2",
    "eu-west-1",
    "eu-central-1",
    "ap-southeast-1",
    "ap-northeast-1",
]


async def discover_enabled_regions(credentials: dict[str, str]) -> list[str]:
    """Discover all enabled AWS regions dynamically."""
    def _fetch():
        ec2 = boto3.client("ec2", region_name="us-east-1", **credentials)
        resp = ec2.describe_regions(AllRegions=False)  # Only enabled regions
        return [r["RegionName"] for r in resp.get("Regions", [])]

    try:
        return await asyncio.to_thread(_fetch)
    except (ClientError, BotoCoreError):
        return DEFAULT_REGIONS

_RETRY_DECORATOR = retry(
    retry=retry_if_exception_type((ClientError, BotoCoreError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)

# CloudWatch metric definitions per resource type
_CW_METRICS: dict[str, list[tuple[str, str, str, list[dict]]]] = {}
# Will be populated dynamically per resource — see _build_cw_dimensions


def _tag_list_to_dict(tags: list[dict] | None) -> dict[str, str]:
    if not tags:
        return {}
    return {t.get("Key", ""): t.get("Value", "") for t in tags}


def _find_name_tag(tags: dict[str, str]) -> str | None:
    return tags.get("Name") or tags.get("name")


class AWSCollector(BaseCollector):
    """Collects resources from a single AWS account using either Role ARN or Access Keys."""

    def __init__(
        self,
        *,
        role_arn: str | None = None,
        external_id: str | None = None,
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        session_name: str = "CostOptimizer",
        regions: list[str] | None = None,
        metric_period_days: int = 30,
    ) -> None:
        if not role_arn and not access_key_id:
            raise ValueError("Either role_arn or access_key_id must be provided")

        self._role_arn = role_arn
        self._external_id = external_id
        self._access_key_id = access_key_id
        self._secret_access_key = secret_access_key
        self._session_name = session_name
        self._regions = regions or DEFAULT_REGIONS
        self._metric_period_days = metric_period_days
        self._credentials: dict[str, str] | None = None
        self._pricing = AWSPricingHelper()
        self._log = logger.bind(auth_mode="access_keys" if access_key_id else "role")

    # ------------------------------------------------------------------
    # Auth helpers
    # ------------------------------------------------------------------

    async def _get_credentials(self) -> dict[str, str]:
        """Get credentials — either from direct keys or via AssumeRole."""
        if self._credentials:
            return self._credentials

        if self._access_key_id:
            self._credentials = {
                "aws_access_key_id": self._access_key_id,
                "aws_secret_access_key": self._secret_access_key,
            }
            self._log.info("using_access_keys")
            return self._credentials

        # AssumeRole path
        @_RETRY_DECORATOR
        def _sts_call() -> dict:
            sts = boto3.client("sts")
            params: dict[str, Any] = {
                "RoleArn": self._role_arn,
                "RoleSessionName": self._session_name,
                "DurationSeconds": 3600,
            }
            if self._external_id:
                params["ExternalId"] = self._external_id
            return sts.assume_role(**params)

        resp = await asyncio.to_thread(_sts_call)
        creds = resp["Credentials"]
        self._credentials = {
            "aws_access_key_id": creds["AccessKeyId"],
            "aws_secret_access_key": creds["SecretAccessKey"],
            "aws_session_token": creds["SessionToken"],
        }
        self._log.info("assumed_role")
        return self._credentials

    def _client(self, service: str, region: str) -> Any:
        """Return a boto3 client using current credentials."""
        if not self._credentials:
            raise RuntimeError("Must call _get_credentials before _client")
        return boto3.client(service, region_name=region, **self._credentials)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def validate_credentials(self) -> bool:
        try:
            creds = await self._get_credentials()
            sts = boto3.client("sts", **creds)
            identity = await asyncio.to_thread(sts.get_caller_identity)
            self._log.info("credentials_valid", account=identity.get("Account"))
            return True
        except (ClientError, BotoCoreError) as exc:
            self._log.error("credentials_invalid", error=str(exc))
            return False

    async def collect_resources(self) -> list[CollectedResource]:
        await self._get_credentials()

        # Discover all enabled regions if using default config
        if self._regions == DEFAULT_REGIONS:
            try:
                discovered = await discover_enabled_regions(self._credentials)
                if discovered:
                    self._regions = discovered
                    self._log.info("discovered_regions", count=len(discovered))
            except Exception:
                pass  # Fall back to defaults

        # Parallel region collection using concurrent tasks
        tasks = [self._collect_region(region) for region in self._regions]
        region_results = await asyncio.gather(*tasks, return_exceptions=True)
        resources: list[CollectedResource] = []
        for idx, result in enumerate(region_results):
            if isinstance(result, Exception):
                self._log.error(
                    "region_collection_failed",
                    region=self._regions[idx],
                    error=str(result),
                )
                continue
            resources.extend(result)
        self._log.info("collection_complete", total_resources=len(resources), regions=len(self._regions))
        return resources

    async def collect_billing(self, start_date: date, end_date: date) -> dict:
        await self._get_credentials()
        return await self._get_cost_explorer(start_date, end_date)

    # ------------------------------------------------------------------
    # Region-level collection
    # ------------------------------------------------------------------

    async def _collect_region(self, region: str) -> list[CollectedResource]:
        self._log.debug("collecting_region", region=region)
        collectors = [
            self._collect_ec2(region),
            self._collect_rds(region),
            self._collect_ebs_volumes(region),
            self._collect_ebs_snapshots(region),
            self._collect_elbs(region),
            self._collect_elastic_ips(region),
        ]
        if region == "us-east-1":
            collectors.append(self._collect_s3())

        results = await asyncio.gather(*collectors, return_exceptions=True)
        resources: list[CollectedResource] = []
        for result in results:
            if isinstance(result, Exception):
                self._log.warning("sub_collector_failed", region=region, error=str(result))
                continue
            resources.extend(result)

        # Collect CloudWatch metrics for all resources in this region
        await self._collect_metrics_for_resources(region, resources)
        return resources

    # ------------------------------------------------------------------
    # EC2
    # ------------------------------------------------------------------

    async def _collect_ec2(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            ec2 = self._client("ec2", region)
            paginator = ec2.get_paginator("describe_instances")
            instances: list[dict] = []
            for page in paginator.paginate():
                for res in page.get("Reservations", []):
                    instances.extend(res.get("Instances", []))
            return instances

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for inst in raw:
            state = inst.get("State", {}).get("Name", "")
            if state == "terminated":
                continue
            tags = _tag_list_to_dict(inst.get("Tags"))
            itype = inst.get("InstanceType", "")
            specs = self._pricing.instance_specs(itype)
            # Extract security group IDs
            sg_ids = [sg.get("GroupId") for sg in inst.get("SecurityGroups", [])]
            # Detect architecture
            arch = inst.get("Architecture", "x86_64")
            # Detect purchase type from instance lifecycle
            lifecycle = inst.get("InstanceLifecycle", "on-demand")  # "spot" or absent (on-demand)

            r = CollectedResource(
                resource_id=inst["InstanceId"],
                resource_type="COMPUTE",
                provider_resource_type="ec2:instance",
                region=region,
                name=_find_name_tag(tags),
                instance_type=itype,
                vcpus=specs.get("vcpus"),
                memory_gb=specs.get("memory_gb"),
                monthly_cost=self._pricing.monthly_cost(itype, region),
                tags=tags,
                metadata={
                    "state": state,
                    "platform": inst.get("Platform", "linux"),
                    "launch_time": inst.get("LaunchTime", "").isoformat()
                    if isinstance(inst.get("LaunchTime"), datetime)
                    else str(inst.get("LaunchTime", "")),
                    "vpc_id": inst.get("VpcId"),
                    "subnet_id": inst.get("SubnetId"),
                    "availability_zone": inst.get("Placement", {}).get("AvailabilityZone"),
                    "architecture": arch,
                    "security_groups": sg_ids,
                    "ebs_optimized": inst.get("EbsOptimized", False),
                    "purchase_type": lifecycle,
                    "iam_profile": (inst.get("IamInstanceProfile") or {}).get("Arn"),
                    "monitoring": inst.get("Monitoring", {}).get("State", "disabled"),
                    "root_device_type": inst.get("RootDeviceType"),
                },
            )
            resources.append(r)

        self._log.debug("ec2_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # RDS
    # ------------------------------------------------------------------

    async def _collect_rds(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            rds = self._client("rds", region)
            paginator = rds.get_paginator("describe_db_instances")
            instances: list[dict] = []
            for page in paginator.paginate():
                instances.extend(page.get("DBInstances", []))
            return instances

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for db in raw:
            itype = db.get("DBInstanceClass", "")
            specs = self._pricing.instance_specs(itype)
            tags = _tag_list_to_dict(db.get("TagList"))
            r = CollectedResource(
                resource_id=db["DBInstanceIdentifier"],
                resource_type="DATABASE",
                provider_resource_type="rds:instance",
                region=region,
                name=db.get("DBInstanceIdentifier"),
                instance_type=itype,
                vcpus=specs.get("vcpus"),
                memory_gb=specs.get("memory_gb"),
                storage_gb=db.get("AllocatedStorage"),
                monthly_cost=self._pricing.monthly_cost(itype, region),
                tags=tags,
                metadata={
                    "engine": db.get("Engine"),
                    "engine_version": db.get("EngineVersion"),
                    "multi_az": db.get("MultiAZ", False),
                    "storage_type": db.get("StorageType"),
                    "status": db.get("DBInstanceStatus"),
                    "encrypted": db.get("StorageEncrypted", False),
                    "backup_retention_period": db.get("BackupRetentionPeriod", 0),
                    "publicly_accessible": db.get("PubliclyAccessible", False),
                    "performance_insights_enabled": db.get("PerformanceInsightsEnabled", False),
                    "auto_minor_version_upgrade": db.get("AutoMinorVersionUpgrade", False),
                    "availability_zone": db.get("AvailabilityZone"),
                    "read_replicas": db.get("ReadReplicaDBInstanceIdentifiers", []),
                    "deletion_protection": db.get("DeletionProtection", False),
                },
            )
            resources.append(r)
        self._log.debug("rds_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # EBS Volumes
    # ------------------------------------------------------------------

    async def _collect_ebs_volumes(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            ec2 = self._client("ec2", region)
            paginator = ec2.get_paginator("describe_volumes")
            volumes: list[dict] = []
            for page in paginator.paginate():
                volumes.extend(page.get("Volumes", []))
            return volumes

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for vol in raw:
            tags = _tag_list_to_dict(vol.get("Tags"))
            size_gb = vol.get("Size", 0)
            vol_type = vol.get("VolumeType", "gp2")
            monthly = self._pricing.ebs_monthly_cost(vol_type, size_gb, vol.get("Iops", 0))
            resources.append(
                CollectedResource(
                    resource_id=vol["VolumeId"],
                    resource_type="VOLUME",
                    provider_resource_type="ebs:volume",
                    region=region,
                    name=_find_name_tag(tags),
                    storage_gb=size_gb,
                    monthly_cost=monthly,
                    tags=tags,
                    metadata={
                        "volume_type": vol_type,
                        "iops": vol.get("Iops"),
                        "throughput": vol.get("Throughput"),
                        "state": vol.get("State"),
                        "attachments": [a.get("InstanceId") for a in vol.get("Attachments", [])],
                        "encrypted": vol.get("Encrypted", False),
                        "availability_zone": vol.get("AvailabilityZone"),
                        "create_time": vol.get("CreateTime", "").isoformat()
                        if isinstance(vol.get("CreateTime"), datetime)
                        else str(vol.get("CreateTime", "")),
                        "multi_attach_enabled": vol.get("MultiAttachEnabled", False),
                    },
                )
            )
        self._log.debug("ebs_volumes_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # EBS Snapshots
    # ------------------------------------------------------------------

    async def _collect_ebs_snapshots(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            ec2 = self._client("ec2", region)
            paginator = ec2.get_paginator("describe_snapshots")
            snaps: list[dict] = []
            for page in paginator.paginate(OwnerIds=["self"]):
                snaps.extend(page.get("Snapshots", []))
            return snaps

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for snap in raw:
            tags = _tag_list_to_dict(snap.get("Tags"))
            size_gb = snap.get("VolumeSize", 0)
            monthly = round(size_gb * 0.05, 2)
            resources.append(
                CollectedResource(
                    resource_id=snap["SnapshotId"],
                    resource_type="SNAPSHOT",
                    provider_resource_type="ebs:snapshot",
                    region=region,
                    name=_find_name_tag(tags) or snap.get("Description"),
                    storage_gb=size_gb,
                    monthly_cost=monthly,
                    tags=tags,
                    metadata={
                        "state": snap.get("State"),
                        "volume_id": snap.get("VolumeId"),
                        "start_time": snap.get("StartTime", "").isoformat()
                        if isinstance(snap.get("StartTime"), datetime)
                        else str(snap.get("StartTime", "")),
                    },
                )
            )
        self._log.debug("ebs_snapshots_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # ELBs (v2 - ALB/NLB)
    # ------------------------------------------------------------------

    async def _collect_elbs(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            elbv2 = self._client("elbv2", region)
            paginator = elbv2.get_paginator("describe_load_balancers")
            lbs: list[dict] = []
            for page in paginator.paginate():
                lbs.extend(page.get("LoadBalancers", []))
            return lbs

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for lb in raw:
            lb_type = lb.get("Type", "application")
            monthly = 22.27
            resources.append(
                CollectedResource(
                    resource_id=lb["LoadBalancerArn"],
                    resource_type="LOAD_BALANCER",
                    provider_resource_type=f"elbv2:{lb_type}",
                    region=region,
                    name=lb.get("LoadBalancerName"),
                    monthly_cost=monthly,
                    metadata={
                        "type": lb_type,
                        "scheme": lb.get("Scheme"),
                        "state": lb.get("State", {}).get("Code"),
                        "dns_name": lb.get("DNSName"),
                        "vpc_id": lb.get("VpcId"),
                        "availability_zones": [az.get("ZoneName") for az in lb.get("AvailabilityZones", [])],
                        "ip_address_type": lb.get("IpAddressType"),
                        "created_time": lb.get("CreatedTime", "").isoformat()
                        if isinstance(lb.get("CreatedTime"), datetime)
                        else str(lb.get("CreatedTime", "")),
                    },
                )
            )
        self._log.debug("elbs_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # Elastic IPs
    # ------------------------------------------------------------------

    async def _collect_elastic_ips(self, region: str) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _describe() -> list[dict]:
            ec2 = self._client("ec2", region)
            return ec2.describe_addresses().get("Addresses", [])

        raw = await asyncio.to_thread(_describe)
        resources: list[CollectedResource] = []
        for addr in raw:
            tags = _tag_list_to_dict(addr.get("Tags"))
            is_associated = addr.get("AssociationId") is not None
            monthly = 0.0 if is_associated else 3.65
            resources.append(
                CollectedResource(
                    resource_id=addr.get("AllocationId", addr.get("PublicIp", "")),
                    resource_type="IP_ADDRESS",
                    provider_resource_type="ec2:elastic_ip",
                    region=region,
                    name=_find_name_tag(tags) or addr.get("PublicIp"),
                    monthly_cost=monthly,
                    tags=tags,
                    metadata={
                        "public_ip": addr.get("PublicIp"),
                        "associated": is_associated,
                        "instance_id": addr.get("InstanceId"),
                        "domain": addr.get("Domain"),
                    },
                )
            )
        self._log.debug("eips_collected", region=region, count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # S3 (global)
    # ------------------------------------------------------------------

    async def _collect_s3(self) -> list[CollectedResource]:
        @_RETRY_DECORATOR
        def _list_buckets() -> list[dict]:
            s3 = self._client("s3", "us-east-1")
            return s3.list_buckets().get("Buckets", [])

        raw = await asyncio.to_thread(_list_buckets)
        resources: list[CollectedResource] = []
        for bucket in raw:
            name = bucket["Name"]
            try:
                loc_resp = await asyncio.to_thread(
                    lambda n=name: self._client("s3", "us-east-1").get_bucket_location(Bucket=n)
                )
                region = loc_resp.get("LocationConstraint") or "us-east-1"
            except ClientError:
                region = "us-east-1"

            # Fetch additional bucket metadata (best-effort)
            s3_client = self._client("s3", "us-east-1")
            versioning = "unknown"
            encryption = "none"
            public_access_blocked = True
            try:
                v_resp = await asyncio.to_thread(
                    lambda n=name: s3_client.get_bucket_versioning(Bucket=n)
                )
                versioning = v_resp.get("Status", "Disabled")
            except ClientError:
                pass
            try:
                e_resp = await asyncio.to_thread(
                    lambda n=name: s3_client.get_bucket_encryption(Bucket=n)
                )
                rules = e_resp.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
                if rules:
                    encryption = rules[0].get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm", "none")
            except ClientError:
                pass
            try:
                pa_resp = await asyncio.to_thread(
                    lambda n=name: s3_client.get_public_access_block(Bucket=n)
                )
                cfg = pa_resp.get("PublicAccessBlockConfiguration", {})
                public_access_blocked = all([
                    cfg.get("BlockPublicAcls", False),
                    cfg.get("IgnorePublicAcls", False),
                    cfg.get("BlockPublicPolicy", False),
                    cfg.get("RestrictPublicBuckets", False),
                ])
            except ClientError:
                pass

            resources.append(
                CollectedResource(
                    resource_id=name,
                    resource_type="STORAGE",
                    provider_resource_type="s3:bucket",
                    region=region,
                    name=name,
                    storage_gb=0,
                    monthly_cost=0.0,
                    metadata={
                        "creation_date": bucket.get("CreationDate", "").isoformat()
                        if isinstance(bucket.get("CreationDate"), datetime)
                        else str(bucket.get("CreationDate", "")),
                        "versioning": versioning,
                        "encryption": encryption,
                        "public_access_blocked": public_access_blocked,
                    },
                )
            )
        self._log.debug("s3_collected", count=len(resources))
        return resources

    # ------------------------------------------------------------------
    # CloudWatch Metrics Collection
    # ------------------------------------------------------------------

    async def _collect_metrics_for_resources(
        self, region: str, resources: list[CollectedResource]
    ) -> None:
        """Collect CloudWatch metrics for all resources in a region."""
        sem = asyncio.Semaphore(5)  # Throttle CW API calls

        async def _fetch_with_sem(resource: CollectedResource) -> None:
            async with sem:
                try:
                    metrics = await self._get_resource_metrics(region, resource)
                    resource.metrics.extend(metrics)
                except Exception as exc:
                    self._log.debug(
                        "metrics_fetch_failed",
                        resource_id=resource.resource_id,
                        error=str(exc),
                    )

        tasks = [_fetch_with_sem(r) for r in resources]
        await asyncio.gather(*tasks)
        self._log.debug(
            "metrics_collected",
            region=region,
            resources_with_metrics=sum(1 for r in resources if r.metrics),
        )

    async def _get_resource_metrics(
        self, region: str, resource: CollectedResource
    ) -> list[CollectedMetric]:
        """Get CloudWatch metrics for a single resource based on its type."""
        metric_defs = self._get_metric_definitions(resource)
        if not metric_defs:
            return []

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=self._metric_period_days)
        metrics: list[CollectedMetric] = []

        for metric_name, namespace, cw_metric, dimensions in metric_defs:
            try:
                m = await self._fetch_cw_metric(
                    region, namespace, cw_metric, dimensions, start, end, metric_name
                )
                if m:
                    metrics.append(m)
            except (ClientError, BotoCoreError) as exc:
                self._log.debug(
                    "cw_metric_failed",
                    metric=cw_metric,
                    resource=resource.resource_id,
                    error=str(exc),
                )
        return metrics

    def _get_metric_definitions(
        self, resource: CollectedResource
    ) -> list[tuple[str, str, str, list[dict]]]:
        """Return (internal_name, namespace, cw_metric_name, dimensions) for a resource."""
        rid = resource.resource_id

        if resource.provider_resource_type == "ec2:instance":
            dims = [{"Name": "InstanceId", "Value": rid}]
            return [
                ("cpu_utilization", "AWS/EC2", "CPUUtilization", dims),
                ("network_in", "AWS/EC2", "NetworkIn", dims),
                ("network_out", "AWS/EC2", "NetworkOut", dims),
                ("disk_read_ops", "AWS/EC2", "DiskReadOps", dims),
                ("disk_write_ops", "AWS/EC2", "DiskWriteOps", dims),
                ("status_check_failed", "AWS/EC2", "StatusCheckFailed", dims),
            ]

        if resource.provider_resource_type == "rds:instance":
            dims = [{"Name": "DBInstanceIdentifier", "Value": rid}]
            return [
                ("cpu_utilization", "AWS/RDS", "CPUUtilization", dims),
                ("database_connections", "AWS/RDS", "DatabaseConnections", dims),
                ("free_storage_space", "AWS/RDS", "FreeStorageSpace", dims),
                ("read_iops", "AWS/RDS", "ReadIOPS", dims),
                ("write_iops", "AWS/RDS", "WriteIOPS", dims),
                ("freeable_memory", "AWS/RDS", "FreeableMemory", dims),
            ]

        if resource.provider_resource_type == "ebs:volume":
            dims = [{"Name": "VolumeId", "Value": rid}]
            return [
                ("disk_iops", "AWS/EBS", "VolumeReadOps", dims),
                ("volume_write_ops", "AWS/EBS", "VolumeWriteOps", dims),
                ("volume_idle_time", "AWS/EBS", "VolumeIdleTime", dims),
            ]

        if resource.provider_resource_type.startswith("elbv2:"):
            # ELB dimensions use the ARN suffix
            arn_suffix = rid.split("loadbalancer/", 1)[-1] if "loadbalancer/" in rid else rid
            dims = [{"Name": "LoadBalancer", "Value": arn_suffix}]
            return [
                ("request_count", "AWS/ApplicationELB", "RequestCount", dims),
                ("target_response_time", "AWS/ApplicationELB", "TargetResponseTime", dims),
                ("healthy_host_count", "AWS/ApplicationELB", "HealthyHostCount", dims),
                ("unhealthy_host_count", "AWS/ApplicationELB", "UnHealthyHostCount", dims),
            ]

        if resource.provider_resource_type == "s3:bucket":
            dims = [
                {"Name": "BucketName", "Value": rid},
                {"Name": "StorageType", "Value": "StandardStorage"},
            ]
            return [
                ("bucket_size_bytes", "AWS/S3", "BucketSizeBytes", dims),
                (
                    "number_of_objects",
                    "AWS/S3",
                    "NumberOfObjects",
                    [
                        {"Name": "BucketName", "Value": rid},
                        {"Name": "StorageType", "Value": "AllStorageTypes"},
                    ],
                ),
            ]

        return []

    async def _fetch_cw_metric(
        self,
        region: str,
        namespace: str,
        metric_name: str,
        dimensions: list[dict],
        start: datetime,
        end: datetime,
        internal_name: str,
    ) -> CollectedMetric | None:
        """Fetch a single CloudWatch metric and compute aggregates."""

        @_RETRY_DECORATOR
        def _get_stats() -> list[dict]:
            cw = self._client("cloudwatch", region)
            resp = cw.get_metric_statistics(
                Namespace=namespace,
                MetricName=metric_name,
                Dimensions=dimensions,
                StartTime=start,
                EndTime=end,
                Period=86400,  # 1 day granularity
                Statistics=["Average", "Maximum", "Minimum"],
            )
            return resp.get("Datapoints", [])

        datapoints = await asyncio.to_thread(_get_stats)
        if not datapoints:
            return None

        avgs = [d["Average"] for d in datapoints]
        maxes = [d["Maximum"] for d in datapoints]
        mins = [d["Minimum"] for d in datapoints]

        # Compute p95 from averages
        p95 = None
        if len(avgs) >= 2:
            sorted_avgs = sorted(avgs)
            idx = int(len(sorted_avgs) * 0.95)
            p95 = sorted_avgs[min(idx, len(sorted_avgs) - 1)]

        return CollectedMetric(
            metric_name=internal_name,
            avg_value=round(statistics.mean(avgs), 4),
            max_value=round(max(maxes), 4),
            min_value=round(min(mins), 4),
            p95_value=round(p95, 4) if p95 is not None else None,
            period_days=self._metric_period_days,
        )

    # ------------------------------------------------------------------
    # Cost Explorer
    # ------------------------------------------------------------------

    async def _get_cost_explorer(self, start_date: date, end_date: date) -> dict:
        @_RETRY_DECORATOR
        def _query() -> dict:
            ce = self._client("ce", "us-east-1")
            resp = ce.get_cost_and_usage(
                TimePeriod={"Start": start_date.isoformat(), "End": end_date.isoformat()},
                Granularity="MONTHLY",
                Metrics=["UnblendedCost", "UsageQuantity"],
                GroupBy=[{"Type": "DIMENSION", "Key": "SERVICE"}],
            )
            results: dict[str, Any] = {"total_cost": 0.0, "by_service": {}, "time_periods": []}
            for period in resp.get("ResultsByTime", []):
                period_start = period["TimePeriod"]["Start"]
                for group in period.get("Groups", []):
                    service = group["Keys"][0]
                    amount = float(group["Metrics"]["UnblendedCost"]["Amount"])
                    results["total_cost"] += amount
                    results["by_service"].setdefault(service, 0.0)
                    results["by_service"][service] += round(amount, 2)
                    results["time_periods"].append(
                        {"start": period_start, "service": service, "cost": round(amount, 2)}
                    )
            results["total_cost"] = round(results["total_cost"], 2)
            return results

        return await asyncio.to_thread(_query)
