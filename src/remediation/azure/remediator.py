from __future__ import annotations

import asyncio
from functools import partial

import structlog
from azure.identity import ClientSecretCredential
from azure.mgmt.compute import ComputeManagementClient
from azure.mgmt.network import NetworkManagementClient

from src.remediation.base import BaseRemediator, RemediationResult

logger = structlog.get_logger(__name__)


class AzureRemediator(BaseRemediator):
    """Azure remediation using azure-mgmt-compute and azure-mgmt-network SDKs."""

    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        subscription_id: str,
    ) -> None:
        self._credential = ClientSecretCredential(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
        )
        self._subscription_id = subscription_id
        self._compute = ComputeManagementClient(self._credential, subscription_id)
        self._network = NetworkManagementClient(self._credential, subscription_id)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_resource_id(resource_id: str) -> tuple[str, str]:
        """Parse 'resource_group/resource_name' into its components."""
        parts = resource_id.split("/", 1)
        if len(parts) != 2:
            raise ValueError(
                f"resource_id must be 'resource_group/name', got: {resource_id}"
            )
        return parts[0], parts[1]

    async def _run(self, fn, *args, **kwargs):
        """Run a synchronous SDK call in a thread."""
        return await asyncio.to_thread(partial(fn, *args, **kwargs))

    # ------------------------------------------------------------------
    # Remediation methods
    # ------------------------------------------------------------------

    async def rightsize_instance(
        self, resource_id: str, target_type: str
    ) -> RemediationResult:
        """Resize an Azure VM: deallocate -> update VM size -> start."""
        rg, vm_name = self._parse_resource_id(resource_id)
        log = logger.bind(resource_group=rg, vm_name=vm_name, target_type=target_type)
        try:
            log.info("azure.vm.resize.start")

            # Deallocate
            poller = await self._run(
                self._compute.virtual_machines.begin_deallocate, rg, vm_name
            )
            await self._run(poller.result)
            log.info("azure.vm.deallocated")

            # Get current VM to capture old size for rollback
            vm = await self._run(self._compute.virtual_machines.get, rg, vm_name)
            old_type = vm.hardware_profile.vm_size

            # Update size
            vm.hardware_profile.vm_size = target_type
            poller = await self._run(
                self._compute.virtual_machines.begin_create_or_update, rg, vm_name, vm
            )
            await self._run(poller.result)

            # Start
            poller = await self._run(
                self._compute.virtual_machines.begin_start, rg, vm_name
            )
            await self._run(poller.result)
            log.info("azure.vm.resize.complete")

            return RemediationResult(
                success=True,
                action="rightsize_instance",
                resource_id=resource_id,
                details=f"Resized VM from {old_type} to {target_type}",
                rollback_info={"old_type": old_type},
            )
        except Exception as exc:
            log.error("azure.vm.resize.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="rightsize_instance",
                resource_id=resource_id,
                details=f"Failed to resize VM: {exc}",
            )

    async def terminate_resource(self, resource_id: str) -> RemediationResult:
        """Delete an Azure VM."""
        rg, vm_name = self._parse_resource_id(resource_id)
        log = logger.bind(resource_group=rg, vm_name=vm_name)
        try:
            log.info("azure.vm.delete.start")
            vm = await self._run(self._compute.virtual_machines.get, rg, vm_name)
            poller = await self._run(
                self._compute.virtual_machines.begin_delete, rg, vm_name
            )
            await self._run(poller.result)
            log.info("azure.vm.delete.complete")

            return RemediationResult(
                success=True,
                action="terminate_resource",
                resource_id=resource_id,
                details=f"Deleted VM {vm_name}",
                rollback_info={"vm_size": vm.hardware_profile.vm_size},
            )
        except Exception as exc:
            log.error("azure.vm.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="terminate_resource",
                resource_id=resource_id,
                details=f"Failed to delete VM: {exc}",
            )

    async def delete_snapshot(self, snapshot_id: str) -> RemediationResult:
        """Delete an Azure managed snapshot."""
        rg, snap_name = self._parse_resource_id(snapshot_id)
        log = logger.bind(resource_group=rg, snapshot_name=snap_name)
        try:
            log.info("azure.snapshot.delete.start")
            poller = await self._run(
                self._compute.snapshots.begin_delete, rg, snap_name
            )
            await self._run(poller.result)
            log.info("azure.snapshot.delete.complete")

            return RemediationResult(
                success=True,
                action="delete_snapshot",
                resource_id=snapshot_id,
                details=f"Deleted snapshot {snap_name}",
            )
        except Exception as exc:
            log.error("azure.snapshot.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="delete_snapshot",
                resource_id=snapshot_id,
                details=f"Failed to delete snapshot: {exc}",
            )

    async def delete_volume(self, volume_id: str) -> RemediationResult:
        """Delete an Azure managed disk."""
        rg, disk_name = self._parse_resource_id(volume_id)
        log = logger.bind(resource_group=rg, disk_name=disk_name)
        try:
            log.info("azure.disk.delete.start")
            poller = await self._run(
                self._compute.disks.begin_delete, rg, disk_name
            )
            await self._run(poller.result)
            log.info("azure.disk.delete.complete")

            return RemediationResult(
                success=True,
                action="delete_volume",
                resource_id=volume_id,
                details=f"Deleted managed disk {disk_name}",
            )
        except Exception as exc:
            log.error("azure.disk.delete.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="delete_volume",
                resource_id=volume_id,
                details=f"Failed to delete managed disk: {exc}",
            )

    async def release_ip(self, ip_id: str) -> RemediationResult:
        """Release an Azure public IP address."""
        rg, ip_name = self._parse_resource_id(ip_id)
        log = logger.bind(resource_group=rg, ip_name=ip_name)
        try:
            log.info("azure.ip.release.start")
            poller = await self._run(
                self._network.public_ip_addresses.begin_delete, rg, ip_name
            )
            await self._run(poller.result)
            log.info("azure.ip.release.complete")

            return RemediationResult(
                success=True,
                action="release_ip",
                resource_id=ip_id,
                details=f"Released public IP {ip_name}",
            )
        except Exception as exc:
            log.error("azure.ip.release.failed", error=str(exc))
            return RemediationResult(
                success=False,
                action="release_ip",
                resource_id=ip_id,
                details=f"Failed to release public IP: {exc}",
            )
