"""Persistent WebSocket relay to the in-container agent (decoupled from browser WS).

Browser disconnects no longer close the upstream connection; the relay runs until
explicit shutdown (session stop/delete) or connection failure.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import update

try:
    import websockets
except ImportError:
    websockets = None  # type: ignore[misc, assignment]

from .agent_relay import connect_agent_websocket, wait_for_fastapi_agent_http
from .database import SessionLocal
from .models import Message
from .schemas import MessageRead
from .ws_manager import session_ws_manager as _manager

logger = logging.getLogger(__name__)

# session_id -> relay (only while agent is active)
_relays: dict[int, SessionAgentRelay] = {}
_session_locks: dict[int, asyncio.Lock] = {}


def normalize_user_chat_content(raw: str) -> str:
    """Store plain user text; unwrap legacy JSON if pasted."""
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


def _lock_for_session(session_id: int) -> asyncio.Lock:
    lock = _session_locks.get(session_id)
    if lock is None:
        lock = asyncio.Lock()
        _session_locks[session_id] = lock
    return lock


class SessionAgentRelay:
    def __init__(self, session_id: int, agent_port: int) -> None:
        self.session_id = session_id
        self.agent_port = agent_port
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._upstream: Any = None
        self._task: asyncio.Task[None] | None = None
        self._start_lock = asyncio.Lock()
        self._client_send_lock = asyncio.Lock()
        self._shutdown_requested = False
        self.assistant_segments: list[str] = []
        self.assistant_lock = asyncio.Lock()
        self._streaming_assistant_message_id: int | None = None

    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def ensure_started(self) -> bool:
        """Probe HTTP, connect upstream, start sender/receiver tasks. Idempotent."""
        if websockets is None:
            await _manager.broadcast(
                self.session_id,
                {
                    "type": "progress",
                    "content": "The assistant connection isn’t available. Please try again later.",
                },
            )
            return False

        async with self._start_lock:
            if self._task is not None and not self._task.done():
                return True
            if self._shutdown_requested:
                return False

            await _manager.broadcast(
                self.session_id,
                {
                    "type": "progress",
                    "content": "Waiting for the remote assistant…",
                },
            )
            http_ok, http_err = await wait_for_fastapi_agent_http(self.agent_port)
            if not http_ok:
                try:
                    await _manager.broadcast(
                        self.session_id,
                        {
                            "type": "progress",
                            "content": http_err
                            or "The assistant isn’t ready yet. Please try again.",
                        },
                    )
                except Exception:
                    pass
                return False

            uri = f"ws://127.0.0.1:{self.agent_port}/ws"
            try:
                await _manager.broadcast(
                    self.session_id,
                    {
                        "type": "progress",
                        "content": "Connecting to the assistant…",
                    },
                )
                self._upstream = await connect_agent_websocket(
                    uri,
                    websockets_module=websockets,
                )
                await _manager.broadcast(
                    self.session_id,
                    {
                        "type": "progress",
                        "content": "Connected. You can send a message.",
                    },
                )
            except Exception:
                logger.exception(
                    "Agent relay connect failed session_id=%s",
                    self.session_id,
                )
                try:
                    await _manager.broadcast(
                        self.session_id,
                        {
                            "type": "progress",
                            "content": "Couldn’t connect to the assistant. Please try again.",
                        },
                    )
                except Exception:
                    pass
                self._upstream = None
                return False

            self._task = asyncio.create_task(
                self._run_gather(), name=f"relay-{self.session_id}"
            )
            return True

    def _sync_persist_combined_unlocked(self, combined: str) -> None:
        """Persist current assistant turn text; INSERT first time, then UPDATE same row.

        Call only with ``assistant_lock`` held so the receiver and user-send paths
        cannot race with segment resets.
        """
        if not combined:
            return
        mid = self._streaming_assistant_message_id
        db = SessionLocal()
        try:
            if mid is None:
                asst = Message(
                    session_id=self.session_id,
                    role="assistant",
                    content=combined,
                    message_kind="progress",
                )
                db.add(asst)
                db.commit()
                db.refresh(asst)
                self._streaming_assistant_message_id = asst.id
            else:
                db.execute(
                    update(Message).where(Message.id == mid).values(content=combined),
                )
                db.commit()
        except Exception:
            logger.exception(
                "Persist assistant transcript failed session_id=%s",
                self.session_id,
            )
            db.rollback()
        finally:
            db.close()

    async def _append_assistant_progress_line(self, payload: object) -> None:
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
        async with self.assistant_lock:
            self.assistant_segments.append(line)
            combined = "\n".join(self.assistant_segments).strip()
            if combined:
                self._sync_persist_combined_unlocked(combined)

    async def handle_client_raw(self, raw: str) -> None:
        """Parse chat, persist user turn, enqueue raw for upstream (serialized per session)."""
        async with self._client_send_lock:
            db = SessionLocal()
            try:
                data = json.loads(raw)
                if data.get("type") == "chat":
                    raw_content = (data.get("content") or "").strip()
                    content = normalize_user_chat_content(raw_content)
                    if content:
                        async with self.assistant_lock:
                            combined = "\n".join(self.assistant_segments).strip()
                            if combined:
                                self._sync_persist_combined_unlocked(combined)
                            self.assistant_segments.clear()
                            self._streaming_assistant_message_id = None
                        user_msg = Message(
                            session_id=self.session_id,
                            role="user",
                            content=content,
                        )
                        db.add(user_msg)
                        db.commit()
                        db.refresh(user_msg)
                        await _manager.broadcast(
                            self.session_id,
                            {
                                "type": "message",
                                "message": MessageRead.model_validate(
                                    user_msg,
                                ).model_dump(mode="json"),
                            },
                        )
            finally:
                db.close()
            await self._queue.put(raw)

    async def _sender(self) -> None:
        assert self._upstream is not None
        while True:
            raw = await self._queue.get()
            try:
                await self._upstream.send(raw)
            except Exception:
                logger.exception("relay sender failed session_id=%s", self.session_id)
                raise

    async def _receiver(self) -> None:
        assert self._upstream is not None
        while True:
            raw = await self._upstream.recv()
            if isinstance(raw, bytes):
                raw = raw.decode()
            payload = json.loads(raw)
            await self._append_assistant_progress_line(payload)
            await _manager.broadcast(self.session_id, payload)

    async def _run_gather(self) -> None:
        assert self._upstream is not None
        sender_task = asyncio.create_task(self._sender())
        receiver_task = asyncio.create_task(self._receiver())
        relay_failed = False
        try:
            await asyncio.gather(sender_task, receiver_task)
        except asyncio.CancelledError:
            raise
        except Exception:
            relay_failed = True
            logger.exception("Agent relay task failed session_id=%s", self.session_id)
        finally:
            for t in (sender_task, receiver_task):
                if not t.done():
                    t.cancel()
            await asyncio.gather(sender_task, receiver_task, return_exceptions=True)
            if relay_failed:
                try:
                    await _manager.broadcast(
                        self.session_id,
                        {
                            "type": "progress",
                            "content": "The assistant connection was lost. Reconnect to continue.",
                        },
                    )
                except Exception:
                    pass
            async with self.assistant_lock:
                combined = "\n".join(self.assistant_segments).strip()
                if combined:
                    self._sync_persist_combined_unlocked(combined)
            if self._upstream is not None:
                try:
                    await self._upstream.close()
                except Exception:
                    pass
                self._upstream = None

    async def shutdown(self) -> None:
        self._shutdown_requested = True
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("relay task join session_id=%s", self.session_id)
        self._task = None
        async with self.assistant_lock:
            combined = "\n".join(self.assistant_segments).strip()
            if combined:
                self._sync_persist_combined_unlocked(combined)
        if self._upstream is not None:
            try:
                await self._upstream.close()
            except Exception:
                pass
            self._upstream = None


async def get_or_create_relay(
    session_id: int, agent_port: int
) -> SessionAgentRelay | None:
    """Return the running relay for this session, starting it if needed."""
    async with _lock_for_session(session_id):
        existing = _relays.get(session_id)
        if existing is not None:
            if existing.agent_port != agent_port:
                logger.warning(
                    "agent_port mismatch session_id=%s expected=%s got=%s",
                    session_id,
                    existing.agent_port,
                    agent_port,
                )
            if existing.is_running():
                return existing
            _relays.pop(session_id, None)
            await existing.shutdown()

        relay = SessionAgentRelay(session_id, agent_port)
        ok = await relay.ensure_started()
        if not ok:
            await relay.shutdown()
            return None
        _relays[session_id] = relay
        return relay


async def shutdown_session_relay(session_id: int) -> None:
    """Stop background relay and close upstream (call on session stop/delete)."""
    async with _lock_for_session(session_id):
        relay = _relays.pop(session_id, None)
    if relay is not None:
        await relay.shutdown()
    _session_locks.pop(session_id, None)
