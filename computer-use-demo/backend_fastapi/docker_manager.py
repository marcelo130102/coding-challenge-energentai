from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import docker
from docker.errors import APIError, ImageNotFound, NotFound

LABEL_MANAGED_KEY = "computer-use-demo.managed"
LABEL_SESSION_KEY = "computer-use-demo.session_id"

COMPUTER_USE_DOCKER_IMAGE = os.getenv(
    "COMPUTER_USE_DOCKER_IMAGE",
    "computer-use-demo:local",
)
NOVNC_HOST_PORT_MIN = int(os.getenv("NOVNC_HOST_PORT_MIN", "6080"))
NOVNC_HOST_PORT_MAX = int(os.getenv("NOVNC_HOST_PORT_MAX", "6200"))
AGENT_API_HOST_PORT_MIN = int(os.getenv("AGENT_API_HOST_PORT_MIN", "8501"))
AGENT_API_HOST_PORT_MAX = int(os.getenv("AGENT_API_HOST_PORT_MAX", "8620"))


def is_orchestration_enabled() -> bool:
    return os.getenv("COMPUTER_USE_ORCHESTRATION", "true").lower() in (
        "1",
        "true",
        "yes",
    )


class DockerOrchestrationError(Exception):
    """Raised when Docker operations for session environments fail."""


@dataclass(frozen=True)
class SessionRuntime:
    container_id: str
    novnc_host_port: int
    agent_api_host_port: int


_lock = threading.Lock()
_used_novnc: set[int] = set()
_used_api: set[int] = set()
_container_ports: dict[str, tuple[int, int]] = {}


def _first_unused(used: set[int], lo: int, hi: int) -> int | None:
    for p in range(lo, hi):
        if p not in used:
            return p
    return None


def _allocate_ports_locked() -> tuple[int, int]:
    n = _first_unused(_used_novnc, NOVNC_HOST_PORT_MIN, NOVNC_HOST_PORT_MAX)
    a = _first_unused(_used_api, AGENT_API_HOST_PORT_MIN, AGENT_API_HOST_PORT_MAX)
    if n is None or a is None:
        msg = "No free host ports in configured NOVNC / AGENT_API ranges"
        raise DockerOrchestrationError(msg)
    _used_novnc.add(n)
    _used_api.add(a)
    return n, a


def _release_ports(novnc: int, api: int) -> None:
    with _lock:
        _used_novnc.discard(novnc)
        _used_api.discard(api)


def _host_ports_from_attrs(attrs: dict) -> tuple[int, int] | None:
    pb = (attrs.get("HostConfig") or {}).get("PortBindings") or {}
    try:
        h6080 = pb["6080/tcp"][0]["HostPort"]
        h8501 = pb["8501/tcp"][0]["HostPort"]
        return int(h6080), int(h8501)
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def sync_port_registry_from_docker() -> None:
    """Rebuild in-memory port sets from running managed containers (after API restart)."""
    client = docker.from_env()
    try:
        running = client.containers.list(
            filters={"label": [f"{LABEL_MANAGED_KEY}=true"]},
        )
    except APIError:
        return
    with _lock:
        _used_novnc.clear()
        _used_api.clear()
        _container_ports.clear()
        for c in running:
            if c.status != "running":
                continue
            pair = _host_ports_from_attrs(c.attrs)
            if pair is None:
                continue
            n, a = pair
            _used_novnc.add(n)
            _used_api.add(a)
            cid = c.id
            if cid:
                _container_ports[cid] = (n, a)


def start_session_environment(session_id: int) -> SessionRuntime:
    """Run a new computer-use container with unique host port mappings."""
    client = docker.from_env()
    with _lock:
        novnc_h, api_h = _allocate_ports_locked()
    container = None
    try:
        container = client.containers.run(
            COMPUTER_USE_DOCKER_IMAGE,
            detach=True,
            name=f"computer-use-session-{session_id}",
            ports={"6080/tcp": novnc_h, "8501/tcp": api_h},
            labels={
                LABEL_MANAGED_KEY: "true",
                LABEL_SESSION_KEY: str(session_id),
            },
        )
    except ImageNotFound as e:
        _release_ports(novnc_h, api_h)
        raise DockerOrchestrationError(
            f"Docker image not found: {COMPUTER_USE_DOCKER_IMAGE}",
        ) from e
    except APIError as e:
        _release_ports(novnc_h, api_h)
        raise DockerOrchestrationError(str(e)) from e
    except Exception:
        _release_ports(novnc_h, api_h)
        if container is not None:
            try:
                container.remove(force=True)
            except APIError:
                pass
        raise

    cid = container.id
    if not cid:
        _release_ports(novnc_h, api_h)
        try:
            container.remove(force=True)
        except APIError:
            pass
        raise DockerOrchestrationError("Container started without an id")

    with _lock:
        _container_ports[cid] = (novnc_h, api_h)

    return SessionRuntime(
        container_id=cid,
        novnc_host_port=novnc_h,
        agent_api_host_port=api_h,
    )


def stop_session_environment(container_id: str) -> None:
    """Stop and remove a session container and release host ports."""
    client = docker.from_env()
    novnc: int | None
    api: int | None
    with _lock:
        pair = _container_ports.pop(container_id, None)
    novnc, api = pair if pair else (None, None)

    try:
        c = client.containers.get(container_id)
        if novnc is None or api is None:
            parsed = _host_ports_from_attrs(c.attrs)
            if parsed:
                novnc, api = parsed
        c.stop(timeout=10)
        c.remove()
    except NotFound:
        pass
    except APIError as e:
        raise DockerOrchestrationError(str(e)) from e
    finally:
        if novnc is not None and api is not None:
            _release_ports(novnc, api)
