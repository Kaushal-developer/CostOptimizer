"""AWS auto-remediation module."""

import asyncio
import boto3
from src.remediation.base import BaseRemediator, RemediationResult
from src.core.logging import logger


class AWSRemediator(BaseRemediator):
    def __init__(self, role_arn: str, external_id: str, region: str = "us-east-1"):
        self.role_arn = role_arn
        self.external_id = external_id
        self.region = region
        self._session = None

    def _get_session(self) -> boto3.Session:
        if self._session is None:
            sts = boto3.client("sts")
            creds = sts.assume_role(
                RoleArn=self.role_arn,
                RoleSessionName="costopt-remediation",
                ExternalId=self.external_id,
            )["Credentials"]
            self._session = boto3.Session(
                aws_access_key_id=creds["AccessKeyId"],
                aws_secret_access_key=creds["SecretAccessKey"],
                aws_session_token=creds["SessionToken"],
                region_name=self.region,
            )
        return self._session

    async def rightsize_instance(self, resource_id: str, target_type: str) -> RemediationResult:
        def _do():
            ec2 = self._get_session().client("ec2")
            # Get current type for rollback
            desc = ec2.describe_instances(InstanceIds=[resource_id])
            current_type = desc["Reservations"][0]["Instances"][0]["InstanceType"]

            # Must stop -> modify -> start
            ec2.stop_instances(InstanceIds=[resource_id])
            waiter = ec2.get_waiter("instance_stopped")
            waiter.wait(InstanceIds=[resource_id])

            ec2.modify_instance_attribute(
                InstanceId=resource_id, InstanceType={"Value": target_type}
            )
            ec2.start_instances(InstanceIds=[resource_id])
            return current_type

        try:
            current_type = await asyncio.to_thread(_do)
            logger.info("AWS rightsize complete", instance=resource_id, new_type=target_type)
            return RemediationResult(
                success=True,
                action="rightsize",
                resource_id=resource_id,
                details=f"Resized from {current_type} to {target_type}",
                rollback_info={"original_type": current_type},
            )
        except Exception as e:
            logger.exception("AWS rightsize failed", instance=resource_id)
            return RemediationResult(
                success=False, action="rightsize", resource_id=resource_id, details=str(e)
            )

    async def terminate_resource(self, resource_id: str) -> RemediationResult:
        def _do():
            ec2 = self._get_session().client("ec2")
            ec2.terminate_instances(InstanceIds=[resource_id])

        try:
            await asyncio.to_thread(_do)
            logger.info("AWS terminate complete", instance=resource_id)
            return RemediationResult(
                success=True, action="terminate", resource_id=resource_id,
                details=f"Terminated {resource_id}",
            )
        except Exception as e:
            logger.exception("AWS terminate failed", instance=resource_id)
            return RemediationResult(
                success=False, action="terminate", resource_id=resource_id, details=str(e)
            )

    async def delete_snapshot(self, snapshot_id: str) -> RemediationResult:
        def _do():
            ec2 = self._get_session().client("ec2")
            ec2.delete_snapshot(SnapshotId=snapshot_id)

        try:
            await asyncio.to_thread(_do)
            return RemediationResult(
                success=True, action="delete_snapshot", resource_id=snapshot_id,
                details=f"Deleted snapshot {snapshot_id}",
            )
        except Exception as e:
            return RemediationResult(
                success=False, action="delete_snapshot", resource_id=snapshot_id, details=str(e)
            )

    async def delete_volume(self, volume_id: str) -> RemediationResult:
        def _do():
            ec2 = self._get_session().client("ec2")
            ec2.delete_volume(VolumeId=volume_id)

        try:
            await asyncio.to_thread(_do)
            return RemediationResult(
                success=True, action="delete_volume", resource_id=volume_id,
                details=f"Deleted volume {volume_id}",
            )
        except Exception as e:
            return RemediationResult(
                success=False, action="delete_volume", resource_id=volume_id, details=str(e)
            )

    async def release_ip(self, ip_id: str) -> RemediationResult:
        def _do():
            ec2 = self._get_session().client("ec2")
            ec2.release_address(AllocationId=ip_id)

        try:
            await asyncio.to_thread(_do)
            return RemediationResult(
                success=True, action="release_ip", resource_id=ip_id,
                details=f"Released Elastic IP {ip_id}",
            )
        except Exception as e:
            return RemediationResult(
                success=False, action="release_ip", resource_id=ip_id, details=str(e)
            )
