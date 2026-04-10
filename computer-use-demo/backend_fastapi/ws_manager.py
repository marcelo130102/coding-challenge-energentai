from __future__ import annotations

from fastapi import WebSocket


class SessionConnectionManager:
    """Keeps WebSocket connections per session for progress and chat events."""

    def __init__(self) -> None:
        self._rooms: dict[int, set[WebSocket]] = {}

    async def connect(self, session_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._rooms.setdefault(session_id, set()).add(websocket)

    def disconnect(self, session_id: int, websocket: WebSocket) -> None:
        room = self._rooms.get(session_id)
        if room:
            room.discard(websocket)
            if not room:
                del self._rooms[session_id]

    async def broadcast(self, session_id: int, payload: object) -> None:
        for ws in list(self._rooms.get(session_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                self.disconnect(session_id, ws)


session_ws_manager = SessionConnectionManager()
