"""WebSocket endpoint with JWT authentication via query param."""

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from jose import JWTError, jwt

from src.core.config import get_settings
from src.api.websocket_manager import ws_manager

router = APIRouter(tags=["websocket"])
settings = get_settings()


def _decode_ws_token(token: str) -> dict | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            return None
        return payload
    except JWTError:
        return None


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, token: str = Query(...)):
    payload = _decode_ws_token(token)
    if not payload:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        await websocket.close(code=4001, reason="No tenant")
        return

    await ws_manager.connect(websocket, tenant_id)
    try:
        while True:
            data = await websocket.receive_json()
            action = data.get("action")
            if action == "subscribe":
                channel = data.get("channel")
                if channel in ("metrics", "costs", "alerts", "compliance", "budgets"):
                    ws_manager.subscribe(websocket, tenant_id, channel)
                    await websocket.send_json({"type": "subscribed", "channel": channel})
            elif action == "unsubscribe":
                channel = data.get("channel")
                if channel:
                    ws_manager.unsubscribe(websocket, tenant_id, channel)
                    await websocket.send_json({"type": "unsubscribed", "channel": channel})
            elif action == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, tenant_id)
    except Exception:
        ws_manager.disconnect(websocket, tenant_id)
