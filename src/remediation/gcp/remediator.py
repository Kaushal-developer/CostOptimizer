from __future__ import annotations

import asyncio
from functools import partial

import structlog
from google.cloud import compute_v1
from google.oauth2 import service_account

from src.remediation.base import BaseRemediator, RemediationResult

logger = structlog.get_logger(__name__)


class GCPRemediator(BaseRemediator):
    """GCP remediation using google-cloud-compute SDK."""

    def __init__(self, project_id: str, credentials_path: str) -> None:
        self._project = project_id
        self._credentials = service_account.Credentials.from_service_account_file(
            credentials_path
        )
        self._instances = compute_v1.InstancesClient(credentials=self._credentials)
        self._snapshots = compute_v1.SnapshotsClient(credentials=self._credentials)
        self._disks = compute_v1.DisksClient(credentials=self._credentials)
        self._addresses = compute_v1.AddressesClient(credentials=self._credentials)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_resource_id(resource_id: str) -> tuple[str, str]:
        """Parse 'zone/resource_name' into its components."""
        parts = resource_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"resource_id must be 'zone/name', got: {resource_id}"
            )
        return parts[0], parts[1]

    @staticmethod
    def _parse_region_resource(resource_id: str) -> tuple[str, str]:
        """Parse 'region/resource_name' for regional resources."""
        parts = resource_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"resource_id must be 'region/name', got: {resource_id}"
            )
        return parts[0], parts[1]

    async def _run(self, fn, *args, **kwargs):
        return await asyncio.to_thread(partial(fn, *args, **kwargs))

    def _wait(self, operation):
        """Block until a zonal/global operation completes (called inside to_thread)."""
        return operation.result()

    # ------------------------------------------------------------------
    # Remediation methods
    # ------------------------------------------------------------------

    async def rightsize_instance(
        self, resource_id: str, target_type: str
    ) -> RemediationResult:
        """Resize a GCE instance: stop -> set machine type -> start."""
        zone, instance_name = self._parse_resource_id(resource_id)
        log = logger.bind(zone=zone, instance=instance_name, target_type=target_type)
        try:
            log.info("gcp.instance.resize.start")

            # Get current instance for rollback info
            instance = await self._run(
                self._instances.get,
                project=self._project,
                zone=zone,
                instance=instance_name,
            )
            old_machine_type = instance.machine_type.rsplit("/", 1)[-1]

            # Stop
            op = await self._run(
                self._instances.stop,
                project=self._project,
                zone=zone,
                instance=instance_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.instance.stopped")

            # Set machine type
            body = compute_v1.InstancesSetMachineTypeRequest(
                machine_type=f"zones/{zone}/machineTypes/{target_type}"
            )
            op = await self._run(
                self._instances.set_machine_type,
                project=self._project,
                zone=zone,
                instance=instance_name,
                instances_set_machine_type_request_resource=body,
            )
            await self._run(self._wait, op)

            # Start
            op = await self._run(
                self._instances.start,
                project=self._project,
                zone=zone,
                instance=instance_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.instance.resize.complete")

            return RemediationResult(
                success=True,
                action="rightsize_instance",
                resource_id=resource_id,
                details=f"Resized instance from {old_machine_type} to {target_type}",
                rollback_info={"old_machine_type": old_machine_type},
            )
        except Exception as exc:
            log.error("gcp.instance.resize.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="rightsize_instance",
                resource_id=resource_id,
                details=f"Failed to resize instance: {exc}",
            )

    async def terminate_resource(self, resource_id: str) -> RemediationResult:
        """Delete a GCE instance."""
        zone, instance_name = self._parse_resource_id(resource_id)
        log = logger.bind(zone=zone, instance=instance_name)
        try:
            log.info("gcp.instance.delete.start")
            instance = await self._run(
                self._instances.get,
                project=self._project,
                zone=zone,
                instance=instance_name,
            )
            old_machine_type = instance.machine_type.rsplit("/", 1)[-1]

            op = await self._run(
                self._instances.delete,
                project=self._project,
                zone=zone,
                instance=instance_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.instance.delete.complete")

            return RemediationResult(
                success=True,
                action="terminate_resource",
                resource_id=resource_id,
                details=f"Deleted instance {instance_name}",
                rollback_info={"machine_type": old_machine_type},
            )
        except Exception as exc:
            log.error("gcp.instance.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="terminate_resource",
                resource_id=resource_id,
                details=f"Failed to delete instance: {exc}",
            )

    async def delete_snapshot(self, snapshot_id: str) -> RemediationResult:
        """Delete a GCE snapshot (global resource, snapshot_id is just the name)."""
        snapshot_name = snapshot_id
        log = logger.bind(snapshot=snapshot_name)
        try:
            log.info("gcp.snapshot.delete.start")
            op = await self._run(
                self._snapshots.delete,
                project=self._project,
                snapshot=snapshot_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.snapshot.delete.complete")

            return RemediationResult(
                success=True,
                action="delete_snapshot",
                resource_id=snapshot_id,
                details=f"Deleted snapshot {snapshot_name}",
            )
        except Exception as exc:
            log.error("gcp.snapshot.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="delete_snapshot",
                resource_id=snapshot_id,
                details=f"Failed to delete snapshot: {exc}",
            )

    async def delete_volume(self, volume_id: str) -> RemediationResult:
        """Delete a GCE persistent disk."""
        zone, disk_name = self._parse_resource_id(volume_id)
        log = logger.bind(zone=zone, disk=disk_name)
        try:
            log.info("gcp.disk.delete.start")
            op = await self._run(
                self._disks.delete,
                project=self._project,
                zone=zone,
                disk=disk_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.disk.delete.complete")

            return RemediationResult(
                success=True,
                action="delete_volume",
                resource_id=volume_id,
                details=f"Deleted disk {disk_name}",
            )
        except Exception as exc:
            log.error("gcp.disk.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="delete_volume",
                resource_id=volume_id,
                details=f"Failed to delete disk: {exc}",
            )

    async def release_ip(self, ip_id: str) -> RemediationResult:
        """Release a GCE static external IP address (regional resource)."""
        region, address_name = self._parse_region_resource(ip_id)
        log = logger.bind(region=region, address=address_name)
        try:
            log.info("gcp.address.release.start")
            op = await self._run(
                self._addresses.delete,
                project=self._project,
                region=region,
                address=address_name,
            )
            await self._run(self._wait, op)
            log.info("gcp.address.release.complete")

            return RemediationResult(
                success=True,
                action="release_ip",
                resource_id=ip_id,
                details=f"Released static IP {address_name}",
            )
        except Exception as exc:
            log.error("gcp.address.release.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="release_ip",
                resource_id=ip_id,
                details=f"Failed to release static IP: {exc}",
            )
