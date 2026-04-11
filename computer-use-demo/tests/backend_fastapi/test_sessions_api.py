from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from backend_fastapi.api_key_crypto import decrypt_session_api_key
from backend_fastapi.docker_manager import DockerOrchestrationError, SessionRuntime
from backend_fastapi.models import Session


def _session_json(**extra: object) -> dict:
    body: dict = {
        "status": "active",
        "api_key": "sk-ant-test-demo",
        "api_endpoint": "global",
    }
    body.update(extra)
    return body


def test_list_sessions_newest_first(sessions_client: TestClient) -> None:
    first = sessions_client.post(
        "/api/sessions",
        json=_session_json(vnc_port=6080),
    ).json()["id"]
    second = sessions_client.post(
        "/api/sessions",
        json=_session_json(vnc_port=6081),
    ).json()["id"]
    r = sessions_client.get("/api/sessions?limit=50")
    assert r.status_code == 200
    ids = [row["id"] for row in r.json()]
    assert second in ids and first in ids
    assert ids.index(second) < ids.index(first)


def test_list_sessions_respects_limit(sessions_client: TestClient) -> None:
    for i in range(3):
        sessions_client.post("/api/sessions", json=_session_json(vnc_port=6080 + i))
    r = sessions_client.get("/api/sessions?limit=2")
    assert r.status_code == 200
    assert len(r.json()) == 2


def test_create_and_get_session(sessions_client: TestClient) -> None:
    r = sessions_client.post(
        "/api/sessions",
        json=_session_json(vnc_port=6085, agent_api_port=8510),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "active"
    assert data["vnc_port"] == 6085
    assert data["agent_api_port"] == 8510
    assert data["docker_container_id"] is None
    assert data["credentials_stored"] is True
    assert data["api_endpoint"] == "global"
    assert "api_key" not in data
    assert "anthropic_base_url" not in data
    sid = data["id"]

    g = sessions_client.get(f"/api/sessions/{sid}")
    assert g.status_code == 200
    gj = g.json()
    assert gj["id"] == sid
    assert "api_key" not in gj


@pytest.mark.usefixtures("test_fernet_key")
def test_create_stores_encrypted_api_key_when_fernet_configured(
    sessions_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPUTER_USE_ORCHESTRATION", "false")
    r = sessions_harness.client.post("/api/sessions", json=_session_json())
    assert r.status_code == 201
    db = sessions_harness.session_factory()
    try:
        row = db.get(Session, r.json()["id"])
        assert row is not None
        assert row.api_key is not None
        assert row.api_key != "sk-ant-test-demo"
        assert decrypt_session_api_key(row.api_key) == "sk-ant-test-demo"
    finally:
        db.close()


def test_create_stores_plaintext_api_key_when_fernet_unset(
    sessions_harness,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SESSION_API_KEY_FERNET_KEY", raising=False)
    monkeypatch.setenv("COMPUTER_USE_ORCHESTRATION", "false")
    r = sessions_harness.client.post("/api/sessions", json=_session_json())
    assert r.status_code == 201
    db = sessions_harness.session_factory()
    try:
        row = db.get(Session, r.json()["id"])
        assert row is not None
        assert row.api_key == "sk-ant-test-demo"
    finally:
        db.close()


def test_get_session_404(sessions_client: TestClient) -> None:
    r = sessions_client.get("/api/sessions/99999")
    assert r.status_code == 404


def test_history_empty(sessions_client: TestClient) -> None:
    created = sessions_client.post("/api/sessions", json=_session_json())
    sid = created.json()["id"]
    r = sessions_client.get(f"/api/sessions/{sid}/history")
    assert r.status_code == 200
    assert r.json() == []


def test_history_404(sessions_client: TestClient) -> None:
    r = sessions_client.get("/api/sessions/42/history")
    assert r.status_code == 404


def test_delete_session(sessions_client: TestClient) -> None:
    sid = sessions_client.post("/api/sessions", json=_session_json()).json()["id"]
    r = sessions_client.delete(f"/api/sessions/{sid}")
    assert r.status_code == 204
    assert sessions_client.get(f"/api/sessions/{sid}").status_code == 404


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
        json=_session_json(vnc_port=6099),
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
    sid = sessions_client.post("/api/sessions", json=_session_json()).json()["id"]
    r = sessions_client.get(f"/api/sessions/{sid}/vnc")
    assert r.status_code == 404
    assert "VNC endpoint" in r.json()["detail"]


def test_get_session_vnc_session_not_found(sessions_client: TestClient) -> None:
    assert sessions_client.get("/api/sessions/99999/vnc").status_code == 404


def test_create_packyapi_endpoint(sessions_client: TestClient) -> None:
    r = sessions_client.post(
        "/api/sessions",
        json=_session_json(api_endpoint="packyapi"),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["api_endpoint"] == "packyapi"
    assert data["credentials_stored"] is True
    assert "api_key" not in data


def test_create_custom_base_url(sessions_client: TestClient) -> None:
    r = sessions_client.post(
        "/api/sessions",
        json=_session_json(
            base_url="https://example.com",
            api_endpoint="global",
        ),
    )
    assert r.status_code == 201
    data = r.json()
    assert data["api_endpoint"] == "custom"
    assert "example.com" not in str(data)
    assert "api_key" not in data


def test_create_orchestration_requires_fernet_key(
    sessions_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("COMPUTER_USE_ORCHESTRATION", "true")
    monkeypatch.delenv("SESSION_API_KEY_FERNET_KEY", raising=False)
    r = sessions_client.post(
        "/api/sessions",
        json=_session_json(status="running"),
    )
    assert r.status_code == 503
    assert "SESSION_API_KEY_FERNET_KEY" in r.json()["detail"]


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
    r = sessions_client.post("/api/sessions", json=_session_json(status="running"))
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "running"
    assert body["vnc_port"] == 6081
    assert body["agent_api_port"] == 8502
    assert body["docker_container_id"] == "deadbeef"
    assert "api_key" not in body
    mock_start.assert_called_once()


@patch("backend_fastapi.routers.sessions.start_session_environment")
def test_create_with_orchestration_fails(
    mock_start: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    mock_start.side_effect = DockerOrchestrationError("no image")
    r = sessions_client.post("/api/sessions", json=_session_json(status="running"))
    assert r.status_code == 503
    assert "no image" in r.json()["detail"]
    mock_start.assert_called_once()


@patch("backend_fastapi.routers.sessions.destroy_session_environment")
def test_delete_calls_destroy_when_container_id(
    mock_destroy: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    with patch(
        "backend_fastapi.routers.sessions.start_session_environment",
        return_value=SessionRuntime("c1", 6082, 8503),
    ):
        sid = sessions_client.post(
            "/api/sessions",
            json=_session_json(status="running"),
        ).json()["id"]

    sessions_client.delete(f"/api/sessions/{sid}")
    mock_destroy.assert_called_once_with("c1")


@patch("backend_fastapi.routers.sessions.pause_session_environment")
@patch("backend_fastapi.routers.sessions.resume_session_environment")
def test_resume_restarts_container(
    mock_resume: object,
    _mock_pause: object,
    sessions_client: TestClient,
    with_docker_orchestration: None,
) -> None:
    mock_resume.return_value = SessionRuntime("c1", 6082, 8503)
    with patch(
        "backend_fastapi.routers.sessions.start_session_environment",
        return_value=SessionRuntime("c1", 6082, 8503),
    ):
        sid = sessions_client.post(
            "/api/sessions",
            json=_session_json(status="running"),
        ).json()["id"]

    st = sessions_client.post(f"/api/sessions/{sid}/stop")
    assert st.status_code == 200
    assert st.json()["status"] == "stopped"
    assert st.json()["docker_container_id"] == "c1"

    r = sessions_client.post(f"/api/sessions/{sid}/resume")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "active"
    assert body["vnc_port"] == 6082
    assert body["agent_api_port"] == 8503
    mock_resume.assert_called_once_with("c1")
