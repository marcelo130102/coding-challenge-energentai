from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[misc, assignment]

from ..agent_relay import connect_agent_websocket, wait_for_fastapi_agent_http
from ..database import SessionLocal
from ..models import Message, Session
from ..schemas import MessageRead
from ..vnc_readiness import on_session_websocket_connected
from ..ws_manager import session_ws_manager as _manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["sessions"])


def _normalize_user_chat_content(raw: str) -> str:
    """Store plain user text; unwrap legacy JSON `{\"type\":\"chat\",\"content\":...}` if pasted."""
    s = raw.strip()
    if not s.startswith("{"):
        return s
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return s
    if not isinstance(obj, dict) or obj.get("type") != "chat":
        return s
    inner = obj.get("content")
    if isinstance(inner, str) and inner.strip():
        return inner.strip()
    return s


async def _relay_ws_to_container_agent(
    websocket: WebSocket,
    session_id: int,
    agent_port: int,
    db,
) -> None:
    """Forward chat JSON to the in-container FastAPI agent (sampling_loop + tools)."""
    if websockets is None:
        await websocket.send_json(
            {
                "type": "progress",
                "content": "The assistant connection isn’t available. Please try again later.",
            },
        )
        return

    await _manager.broadcast(
        session_id,
        {
            "type": "progress",
            "content": "Waiting for the remote assistant…",
        },
    )
    http_ok, http_err = await wait_for_fastapi_agent_http(agent_port)
    if not http_ok:
        try:
            await _manager.broadcast(
                session_id,
                {
                    "type": "progress",
                    "content": http_err or "The assistant isn’t ready yet. Please try again.",
                },
            )
        except Exception:
            pass
        return

    uri = f"ws://127.0.0.1:{agent_port}/ws"
    upstream = None
    assistant_segments: list[str] = []
    assistant_lock = asyncio.Lock()

    async def flush_assistant_to_db() -> None:
        """Persist streamed agent progress as one assistant row before the next user turn."""
        async with assistant_lock:
            if not assistant_segments:
                return
            combined = "\n".join(assistant_segments).strip()
            assistant_segments.clear()
        if not combined:
            return
        try:
            asst = Message(
                session_id=session_id,
                role="assistant",
                content=combined,
            )
            db.add(asst)
            db.commit()
        except Exception:
            logger.exception(
                "Persist assistant transcript failed session_id=%s",
                session_id,
            )
            db.rollback()

    async def append_assistant_progress_line(payload: object) -> None:
        if not isinstance(payload, dict):
            return
        if payload.get("type") != "progress":
            return
        c = payload.get("content")
        if not isinstance(c, str):
            return
        line = c.strip()
        if not line:
            return
        async with assistant_lock:
            assistant_segments.append(line)

    try:
        await _manager.broadcast(
            session_id,
            {
                "type": "progress",
                "content": "Connecting to the assistant…",
            },
        )
        upstream = await connect_agent_websocket(uri, websockets_module=websockets)
        await _manager.broadcast(
            session_id,
            {
                "type": "progress",
                "content": "Connected. You can send a message.",
            },
        )

        async def pump_client_to_agent() -> None:
            while True:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                if data.get("type") == "chat":
                    raw_content = (data.get("content") or "").strip()
                    content = _normalize_user_chat_content(raw_content)
                    if content:
                        await flush_assistant_to_db()
                        user_msg = Message(
                            session_id=session_id,
                            role="user",
                            content=content,
                        )
                        db.add(user_msg)
                        db.commit()
                        db.refresh(user_msg)
                        await _manager.broadcast(
                            session_id,
                            {
                                "type": "message",
                                "message": MessageRead.model_validate(
                                    user_msg,
                                ).model_dump(mode="json"),
                            },
                        )
                await upstream.send(raw)

        async def pump_agent_to_room() -> None:
            while True:
                raw = await upstream.recv()
                if isinstance(raw, bytes):
                    raw = raw.decode()
                payload = json.loads(raw)
                await append_assistant_progress_line(payload)
                await _manager.broadcast(session_id, payload)

        try:
            await asyncio.gather(
                pump_client_to_agent(),
                pump_agent_to_room(),
            )
        finally:
            await flush_assistant_to_db()
    except Exception as e:
        logger.exception("Agent relay failed session_id=%s", session_id)
        try:
            await _manager.broadcast(
                session_id,
                {
                    "type": "progress",
                    "content": "Couldn’t connect to the assistant. Please try again.",
                },
            )
        except Exception:
            pass
    finally:
        if upstream is not None:
            try:
                await upstream.close()
            except Exception:
                pass


@router.websocket("/{session_id}/ws")
async def session_events(websocket: WebSocket, session_id: int) -> None:
    """Chat WebSocket: proxies to the container agent (Anthropic sampling_loop) when orchestrated."""
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
                "message": "You’re connected. Type a message below and press Send.",
                "session_id": session_id,
            },
        )
        row = db.get(Session, session_id)
        vnc_port = row.vnc_port if row is not None else None
        agent_port = row.agent_api_port if row is not None else None

        await on_session_websocket_connected(session_id, vnc_port, websocket)

        if agent_port is not None:
            await _relay_ws_to_container_agent(
                websocket,
                session_id,
                agent_port,
                db,
            )
            return

        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break
            if data.get("type") != "chat":
                continue
            content = _normalize_user_chat_content(
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
