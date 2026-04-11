"""WebSocket chat path (no Docker; in-memory DB via ``chat_websocket_client``)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_websocket_demo_chat_round_trip(chat_websocket_client: TestClient) -> None:
    """Non-orchestrated session: agent relay off; server stores user msg and demo assistant reply."""
    created = chat_websocket_client.post(
        "/api/sessions",
        json={
            "status": "active",
            "api_key": "sk-ant-ws-test",
            "api_endpoint": "global",
        },
    )
    assert created.status_code == 201
    sid = created.json()["id"]

    with chat_websocket_client.websocket_connect(f"/api/sessions/{sid}/ws") as ws:
        first = ws.receive_json()
        assert first["type"] == "progress"

        ws.send_json({"type": "chat", "content": "Hello WS"})

        chunks: list[dict] = []
        for _ in range(3):
            chunks.append(ws.receive_json())

        types = [c.get("type") for c in chunks]
        assert "message" in types
        roles = [
            c["message"]["role"]
            for c in chunks
            if c.get("type") == "message" and "message" in c
        ]
        assert "user" in roles
        assert "assistant" in roles
        assistant = next(
            c["message"]
            for c in chunks
            if c.get("type") == "message"
            and c.get("message", {}).get("role") == "assistant"
        )
        assert "(demo reply)" in assistant["content"]
