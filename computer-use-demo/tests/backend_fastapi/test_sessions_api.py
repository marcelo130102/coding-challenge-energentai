from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend_fastapi.docker_manager import DockerOrchestrationError, SessionRuntime


def test_create_and_get_session(sessions_client: TestClient) -> None:
    r = sessions_client.post(
        "/api/sessions",
        json={"status": "active", "vnc_port": 6085, "agent_api_port": 8510},
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "active"
    assert data["vnc_port"] == 6085
    assert data["agent_api_port"] == 8510
    assert data["docker_container_id"] is None
    sid = data["id"]

    g = sessions_client.get(f"/api/sessions/{sid}")
    assert g.status_code == 200
    assert g.json()["id"] == sid


def test_get_session_404(sessions_client: TestClient) -> None:
    r = sessions_client.get("/api/sessions/99999")
    assert r.status_code == 404


def test_history_empty(sessions_client: TestClient) -> None:
    created = sessions_client.post("/api/sessions", json={"status": "active"})
    sid = created.json()["id"]
    r = sessions_client.get(f"/api/sessions/{sid}/history")
    assert r.status_code == 200
    assert r.json() == []


def test_history_404(sessions_client: TestClient) -> None:
    r = sessions_client.get("/api/sessions/42/history")
    assert r.status_code == 404


def test_delete_session(sessions_client: TestClient) -> None:
    sid = sessions_client.post("/api/sessions", json={"status": "active"}).json()["id"]
    r = sessions_client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    assert r.json()["vnc_port"] is None
    assert sessions_client.get(f"/api/sessions/{sid}").status_code == 200


def test_delete_session_404(sessions_client: TestClient) -> None:
    assert sessions_client.delete("/api/sessions/99999").status_code == 404


def test_get_session_vnc_urls(
    sessions_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import backend_fastapi.novnc_urls as nu

    monkeypatch.setattr(nu, "NOVNC_PUBLIC_HOST", "example.test")
    monkeypatch.setattr(nu, "NOVNC_PUBLIC_WS_SCHEME", "ws")
    monkeypatch.setattr(nu, "NOVNC_PUBLIC_HTTP_SCHEME", "http")
    monkeypatch.setattr(nu, "NOVNC_WEBSOCKET_PATH", "websockify")

    sid = sessions_client.post(
        "/api/sessions",
        json={"status": "active", "vnc_port": 6099},
    ).json()["id"]
    r = sessions_client.get(f"/api/sessions/{sid}/vnc")
    assert r.status_code == 200
    body = r.json()
    assert body["session_id"] == sid
    assert body["websocket_url"] == "ws://example.test:6099/websockify"
    assert "vnc.html" in body["http_url"]
    assert "6099" in body["http_url"]
    assert "autoconnect=1" in body["http_url"]


def test_get_session_vnc_no_port(sessions_client: TestClient) -> None:
    sid = sessions_client.post("/api/sessions", json={"status": "active"}).json()["id"]
    r = sessions_client.get(f"/api/sessions/{sid}/vnc")
    assert r.status_code == 404
    assert "VNC endpoint" in r.json()["detail"]


def test_get_session_vnc_session_not_found(sessions_client: TestClient) -> None:
    assert sessions_client.get("/api/sessions/99999/vnc").status_code == 404


@patch("backend_fastapi.routers.sessions.start_session_environment")
def test_create_with_orchestration_success(
    mock_start: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    mock_start.return_value = SessionRuntime(
        container_id="deadbeef",
        novnc_host_port=6081,
        agent_api_host_port=8502,
    )
    r = sessions_client.post("/api/sessions", json={"status": "running"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert body["vnc_port"] == 6081
    assert body["agent_api_port"] == 8502
    assert body["docker_container_id"] == "deadbeef"
    mock_start.assert_called_once()


@patch("backend_fastapi.routers.sessions.start_session_environment")
def test_create_with_orchestration_fails(
    mock_start: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    mock_start.side_effect = DockerOrchestrationError("no image")
    r = sessions_client.post("/api/sessions", json={"status": "running"})
    assert r.status_code == 503
    assert "no image" in r.json()["detail"]
    mock_start.assert_called_once()


@patch("backend_fastapi.routers.sessions.stop_session_environment")
def test_delete_calls_stop_when_container_id(
    mock_stop: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    with patch(
        "backend_fastapi.routers.sessions.start_session_environment",
        return_value=SessionRuntime("c1", 6082, 8503),
    ):
        sid = sessions_client.post(
            "/api/sessions",
            json={"status": "running"},
        ).json()["id"]

    sessions_client.delete(f"/api/sessions/{sid}")
    mock_stop.assert_called_once_with("c1")
