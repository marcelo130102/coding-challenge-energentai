from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import Message, Session
from ..schemas import MessageRead
from ..session_relay_manager import (
    SessionAgentRelay,
    get_or_create_relay,
    normalize_user_chat_content,
)
from ..vnc_readiness import on_session_websocket_connected
from ..ws_manager import session_ws_manager as _manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.websocket("/{session_id}/ws")
async def session_events(websocket: WebSocket, session_id: int) -> None:
    """Chat WebSocket: proxies to the container agent (Anthropic sampling_loop) when orchestrated."""
    db = SessionLocal()
    try:
        row = db.get(Session, session_id)
        if row is None:
            await websocket.accept()
            await websocket.close(code=1008, reason="Session not found")
            return
        await _manager.connect(session_id, websocket)
        if row.status == "stopped":
            await websocket.send_json(
                {
                    "type": "progress",
                    "content": (
                        "This session is stopped. Use Resume in the sidebar "
                        "to start the desktop and chat again."
                    ),
                    "session_id": session_id,
                },
            )
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            return

        await websocket.send_json(
            {
                "type": "progress",
                "message": "You’re connected. Type a message below and press Send.",
                "session_id": session_id,
            },
        )
        vnc_port = row.vnc_port if row is not None else None
        agent_port = row.agent_api_port if row is not None else None

        await on_session_websocket_connected(session_id, vnc_port, websocket)

        if agent_port is not None:
            relay: SessionAgentRelay | None = await get_or_create_relay(
                session_id,
                agent_port,
            )
            if relay is None:
                while True:
                    await websocket.receive_text()
            else:
                try:
                    while True:
                        raw = await websocket.receive_text()
                        active = relay
                        if not active.is_running():
                            active = await get_or_create_relay(
                                session_id,
                                agent_port,
                            )
                        if active is None:
                            continue
                        relay = active
                        await active.handle_client_raw(raw)
                except WebSocketDisconnect:
                    pass
            return

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            if data.get("type") != "chat":
                continue
            content = normalize_user_chat_content(
                (data.get("content") or "").strip(),
            )
            if not content:
                continue

            user_msg = Message(session_id=session_id, role="user", content=content)
            db.add(user_msg)
            db.commit()
            db.refresh(user_msg)
            await _manager.broadcast(
                session_id,
                {
                    "type": "message",
                    "message": MessageRead.model_validate(user_msg).model_dump(
                        mode="json",
                    ),
                },
            )
            await _manager.broadcast(
                session_id,
                {"type": "progress", "content": "Working on it…"},
            )
            reply = Message(
                session_id=session_id,
                role="assistant",
                content=f"(demo reply) {content[:800]}",
            )
            db.add(reply)
            db.commit()
            db.refresh(reply)
            await _manager.broadcast(
                session_id,
                {
                    "type": "message",
                    "message": MessageRead.model_validate(reply).model_dump(
                        mode="json",
                    ),
                },
            )
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected session_id=%s", session_id)
    finally:
        _manager.disconnect(session_id, websocket)
        db.close()
