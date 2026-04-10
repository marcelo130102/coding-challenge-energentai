from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..database import SessionLocal
from ..models import Message, Session
from ..schemas import MessageRead
from ..ws_manager import session_ws_manager as _manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.websocket("/{session_id}/ws")
async def session_events(websocket: WebSocket, session_id: int) -> None:
    """Stream progress and chat events; client sends JSON: {\"type\":\"chat\",\"content\":\"...\"}."""
    db = SessionLocal()
    try:
        if db.get(Session, session_id) is None:
            await websocket.accept()
            await websocket.close(code=1008, reason="Session not found")
            return
        await _manager.connect(session_id, websocket)
        await websocket.send_json(
            {
                "type": "progress",
                "message": "Connected to session. Send chat messages as JSON: "
                '{"type":"chat","content":"your text"}',
                "session_id": session_id,
            },
        )
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            if data.get("type") != "chat":
                continue
            content = (data.get("content") or "").strip()
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
                {"type": "progress", "content": "Agent working (demo)…"},
            )
            reply = Message(
                session_id=session_id,
                role="assistant",
                content=f"(demo) {content[:800]}",
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
