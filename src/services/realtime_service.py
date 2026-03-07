"""Real-time service for pushing metrics to WebSocket clients."""

from __future__ import annotations

import asyncio
import random
from datetime import datetime, timezone
from src.api.websocket_manager import ws_manager
import structlog

logger = structlog.get_logger(__name__)

_background_task: asyncio.Task | None = None


async def _push_metrics_loop():
    """Background loop pushing simulated real-time metrics."""
    while True:
        try:
            # Push to all tenants that have subscribers
            for tenant_id in list(ws_manager._subscriptions.keys()):
                if ws_manager._subscriptions[tenant_id].get("metrics"):
                    await ws_manager.broadcast_to_channel(tenant_id, "metrics", {
                        "type": "metric_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "metrics": {
                            "cpu_avg": round(random.uniform(15, 85), 1),
                            "memory_avg": round(random.uniform(30, 90), 1),
                            "network_in_mbps": round(random.uniform(10, 500), 1),
                            "network_out_mbps": round(random.uniform(5, 200), 1),
                            "active_instances": random.randint(5, 50),
                            "cost_per_hour": round(random.uniform(0.5, 15.0), 2),
                        },
                    })

                if ws_manager._subscriptions[tenant_id].get("costs"):
                    await ws_manager.broadcast_to_channel(tenant_id, "costs", {
                        "type": "cost_update",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "today_spend": round(random.uniform(50, 500), 2),
                        "projected_monthly": round(random.uniform(1500, 15000), 2),
                    })
        except Exception as e:
            logger.warning("realtime_push_error", error=str(e))

        await asyncio.sleep(5)


def start_realtime_service():
    global _background_task
    if _background_task is None or _background_task.done():
        _background_task = asyncio.create_task(_push_metrics_loop())
        logger.info("realtime_service_started")


def stop_realtime_service():
    global _background_task
    if _background_task and not _background_task.done():
        _background_task.cancel()
        _background_task = None
