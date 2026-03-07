"""Base remediation interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class RemediationResult:
    success: bool
    action: str
    resource_id: str
    details: str
    rollback_info: dict | None = None


class BaseRemediator(ABC):
    @abstractmethod
    async def rightsize_instance(self, resource_id: str, target_type: str) -> RemediationResult:
        ...

    @abstractmethod
    async def terminate_resource(self, resource_id: str) -> RemediationResult:
        ...

    @abstractmethod
    async def delete_snapshot(self, snapshot_id: str) -> RemediationResult:
        ...

    @abstractmethod
    async def delete_volume(self, volume_id: str) -> RemediationResult:
        ...

    @abstractmethod
    async def release_ip(self, ip_id: str) -> RemediationResult:
        ...
