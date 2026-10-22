"""The live telemetry socket.

One connection carries every topic. Server-to-client only — commands go over REST — so
the client needs no request/response correlation, just a topic switch.
"""

import asyncio
import contextlib

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import ALLOWED_ORIGINS
from ..realtime import TOPIC_SESSION
from ..state import AppState

log = structlog.get_logger(__name__)

router = APIRouter(tags=["realtime"])

#: Nudge the socket periodically so a dead connection is noticed rather than lingering.
HEARTBEAT_SECONDS = 25.0


#: Hosts the app itself is reached at.
LOCAL_HOSTS = ("localhost", "127.0.0.1")


def same_app(origin: str | None, host: str | None) -> bool:
    """The page is one of the app's own: a known origin, or the address this socket was
    opened on when that is this computer (the app run on another port)."""
    if origin in ALLOWED_ORIGINS:
        return True
    if not origin or not host or host.split(":", 1)[0] not in LOCAL_HOSTS:
        return False
    return origin == f"http://{host}"


@router.websocket("/ws")
async def telemetry(websocket: WebSocket) -> None:
    # WebSocket routes get no Request, so reach the composition root off the app.
    state: AppState = websocket.app.state.harness
    # Browsers always send Origin on a handshake, and CORS does not cover sockets: without
    # this any page the user visits could open one. Missing and "null" fail the same test.
    if not same_app(websocket.headers.get("origin"), websocket.headers.get("host")):
        await websocket.close(code=1008)
        return
    await state.hub.connect(websocket)

    try:
        # The session is sent fresh: it may never have been broadcast since startup.
        await websocket.send_json({"topic": TOPIC_SESSION, "payload": state.auth.session.to_dict()})

        while True:
            try:
                # Any inbound frame is treated as a keepalive; there are no commands.
                await asyncio.wait_for(websocket.receive_text(), timeout=HEARTBEAT_SECONDS)
            except TimeoutError:
                await websocket.send_json({"topic": "ping", "payload": None})
    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("ws.closed_unexpectedly", exc_info=True)
    finally:
        state.hub.disconnect(websocket)
        with contextlib.suppress(Exception):
            await websocket.close()
