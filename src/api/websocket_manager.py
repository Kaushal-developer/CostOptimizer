"""WebSocket connection manager with per-tenant channels."""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from fastapi import WebSocket
import structlog

logger = structlog.get_logger(__name__)


class ConnectionManager:
    _instance: ConnectionManager | None = None

    def __new__(cls) -> ConnectionManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._connections: dict[int, list[WebSocket]] = defaultdict(list)
            cls._instance._subscriptions: dict[int, dict[str, set[WebSocket]]] = defaultdict(lambda: defaultdict(set))
        return cls._instance

    async def connect(self, websocket: WebSocket, tenant_id: int) -> None:
        await websocket.accept()
        self._connections[tenant_id].append(websocket)
        logger.info("ws_connected", tenant_id=tenant_id)

    def disconnect(self, websocket: WebSocket, tenant_id: int) -> None:
        if websocket in self._connections[tenant_id]:
            self._connections[tenant_id].remove(websocket)
        for channel_subs in self._subscriptions[tenant_id].values():
            channel_subs.discard(websocket)
        logger.info("ws_disconnected", tenant_id=tenant_id)

    def subscribe(self, websocket: WebSocket, tenant_id: int, channel: str) -> None:
        self._subscriptions[tenant_id][channel].add(websocket)

    def unsubscribe(self, websocket: WebSocket, tenant_id: int, channel: str) -> None:
        self._subscriptions[tenant_id][channel].discard(websocket)

    async def broadcast_to_tenant(self, tenant_id: int, message: dict) -> None:
        dead = []
        for ws in self._connections.get(tenant_id, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, tenant_id)

    async def broadcast_to_channel(self, tenant_id: int, channel: str, message: dict) -> None:
        dead = []
        for ws in self._subscriptions.get(tenant_id, {}).get(channel, set()):
            try:
                await ws.send_json({"channel": channel, **message})
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, tenant_id)

    async def broadcast_all(self, message: dict) -> None:
        tasks = [self.broadcast_to_tenant(tid, message) for tid in self._connections]
        await asyncio.gather(*tasks, return_exceptions=True)

    def get_connection_count(self, tenant_id: int | None = None) -> int:
        if tenant_id is not None:
            return len(self._connections.get(tenant_id, []))
        return sum(len(v) for v in self._connections.values())


ws_manager = ConnectionManager()
