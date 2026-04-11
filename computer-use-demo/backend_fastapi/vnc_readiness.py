"""Probe host-published noVNC ports and notify WebSocket clients when the desktop is reachable."""

from __future__ import annotations

import asyncio
import http.client
import logging
import os
import time
from typing import Any

from fastapi import WebSocket

from .novnc_urls import build_session_vnc_info
from .ws_manager import session_ws_manager as _manager

logger = logging.getLogger(__name__)

_lock = asyncio.Lock()
_ready_payload: dict[int, dict[str, Any]] = {}
_tasks: dict[int, asyncio.Task[None]] = {}

VNC_PROBE_INTERVAL_S = 0.5
VNC_PROBE_TIMEOUT_S = 120.0
# After HTTP serves vnc.html, websockify may still need a moment before the browser WebSocket
# (autoconnect=1) succeeds; without settle time, noVNC often shows Failed to connect until Connect.
VNC_POST_HTTP_SETTLE_S = float(os.getenv("VNC_POST_HTTP_SETTLE_S", "2.0"))
_HTTP_GET_TIMEOUT_S = 4.0


def _http_get_vnc_html_ok(host: str, port: int) -> bool:
    """True when the noVNC web UI is actually being served (not only an open TCP port)."""
    try:
        conn = http.client.HTTPConnection(host, port, timeout=_HTTP_GET_TIMEOUT_S)
        conn.request("GET", "/vnc.html")
        resp = conn.getresponse()
        resp.read(256)
        status = resp.status
        conn.close()
        return status == 200
    except Exception:
        return False


async def _novnc_http_ready(host: str, port: int) -> bool:
    return await asyncio.to_thread(_http_get_vnc_html_ok, host, port)


async def _probe_task(session_id: int, vnc_port: int) -> None:
    try:
        deadline = time.monotonic() + VNC_PROBE_TIMEOUT_S
        await _manager.broadcast(
            session_id,
            {
                "type": "progress",
                "content": "Waiting for the remote desktop…",
            },
        )
        while time.monotonic() < deadline:
            if await _novnc_http_ready("127.0.0.1", vnc_port):
                await _manager.broadcast(
                    session_id,
                    {
                        "type": "progress",
                        "content": "Almost ready…",
                    },
                )
                await asyncio.sleep(VNC_POST_HTTP_SETTLE_S)
                info = build_session_vnc_info(session_id, vnc_port)
                out: dict[str, Any] = {
                    "type": "vnc_ready",
                    "session_id": session_id,
                    "http_url": info.http_url,
                    "websocket_url": info.websocket_url,
                }
                async with _lock:
                    _ready_payload[session_id] = out
                await _manager.broadcast(session_id, out)
                return
            await asyncio.sleep(VNC_PROBE_INTERVAL_S)
        await _manager.broadcast(
            session_id,
            {
                "type": "vnc_timeout",
                "session_id": session_id,
                "content": "The remote desktop didn’t load in time. Try opening it in a new tab.",
            },
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("vnc probe failed session_id=%s", session_id)
    finally:
        async with _lock:
            _tasks.pop(session_id, None)


def clear_session(session_id: int) -> None:
    """Cancel noVNC probe tasks and drop cached payloads when a session row is removed."""
    task = _tasks.pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()
    _ready_payload.pop(session_id, None)


async def on_session_websocket_connected(
    session_id: int,
    vnc_port: int | None,
    websocket: WebSocket,
) -> None:
    """Notify this client when noVNC serves /vnc.html and settles; reuses cached payload if ready."""
    if vnc_port is None:
        return
    async with _lock:
        cached = _ready_payload.get(session_id)
    if cached:
        try:
            await websocket.send_json(cached)
        except Exception:
            pass
        return
    async with _lock:
        existing = _tasks.get(session_id)
        starting = existing is None or existing.done()
        if starting:
            _tasks[session_id] = asyncio.create_task(_probe_task(session_id, vnc_port))
        else:
            try:
                await websocket.send_json(
                    {
                        "type": "progress",
                        "content": "Still connecting to the desktop…",
                    },
                )
            except Exception:
                pass
