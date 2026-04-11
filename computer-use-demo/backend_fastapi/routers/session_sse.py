"""Server-Sent Events (SSE) for session status (server→client only).

This module intentionally avoids coupling to :mod:`ws_manager` (WebSocket chat relay).
It polls persisted session state from the database on an interval and emits ``status``
events. Future work: bridge ``SessionConnectionManager.broadcast`` (or a shared
async queue) here to stream the same progress payloads as WebSockets without polling.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session as OrmSession

from ..database import SessionLocal
from ..models import Session

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _sse_frame(*, event: str | None, data: object) -> str:
    lines: list[str] = []
    if event:
        lines.append(f"event: {event}")
    lines.append(f"data: {json.dumps(data, default=str)}")
    lines.append("")
    return "\n".join(lines) + "\n"


def _status_payload(row: Session) -> dict[str, object]:
    return {
        "type": "session_status",
        "session_id": row.id,
        "status": row.status,
        "created_at": row.created_at.isoformat(),
        "vnc_port": row.vnc_port,
        "agent_api_port": row.agent_api_port,
        "docker_container_id": row.docker_container_id,
        "api_endpoint": row.api_endpoint,
    }


async def _session_status_event_stream(
    session_id: int,
    *,
    interval_s: float,
    heartbeat_every_n: int,
) -> AsyncIterator[str]:
    """Poll DB for session row; emit ``status`` events + occasional comment heartbeats."""
    tick = 0
    while True:
        db: OrmSession = SessionLocal()
        try:
            row = db.get(Session, session_id)
            if row is None:
                yield _sse_frame(
                    event="error",
                    data={"detail": "Session not found", "session_id": session_id},
                )
                return
            yield _sse_frame(event="status", data=_status_payload(row))
        finally:
            db.close()

        tick += 1
        if heartbeat_every_n > 0 and tick % heartbeat_every_n == 0:
            yield ": heartbeat\n\n"

        await asyncio.sleep(interval_s)


@router.get("/{session_id}/events")
async def session_server_sent_events(
    session_id: int,
    interval_s: Annotated[
        float,
        Query(
            ge=1.0,
            le=120.0,
            description="Seconds between database polls (status snapshots).",
        ),
    ] = 3.0,
    heartbeat_every_n: Annotated[
        int,
        Query(
            ge=0,
            le=100,
            description="Emit an SSE comment heartbeat every N polls (0 disables).",
        ),
    ] = 5,
) -> StreamingResponse:
    """
    Subscribe to **server→client** session status updates over SSE (``text/event-stream``).

    Scope is intentionally narrow: **persisted** session fields (status, ports, etc.),
    not full chat or agent tool streams. Use WebSocket ``/api/sessions/{id}/ws`` for
    bidirectional chat and agent relay traffic.

    **Extension point:** push live ``ws_manager``-style progress by registering a
    subscriber queue and merging async yields with this loop (or replacing polling).
    """
    return StreamingResponse(
        _session_status_event_stream(
            session_id,
            interval_s=interval_s,
            heartbeat_every_n=heartbeat_every_n,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
