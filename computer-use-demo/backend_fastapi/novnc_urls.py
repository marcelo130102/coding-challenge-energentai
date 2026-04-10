from __future__ import annotations

import os
from urllib.parse import quote

from .schemas import SessionVncInfo

# Hostname the browser uses to reach noVNC (must match Docker port publishing).
# Override when the API is behind DNS or a tunnel (e.g. ngrok host only for noVNC).
NOVNC_PUBLIC_HOST = os.getenv("NOVNC_PUBLIC_HOST", "localhost")
# ws | wss — use wss when TLS terminates on the same host:port as noVNC.
NOVNC_PUBLIC_WS_SCHEME = os.getenv("NOVNC_PUBLIC_WS_SCHEME", "ws")
# http | https — page URL for iframe embedding.
NOVNC_PUBLIC_HTTP_SCHEME = os.getenv("NOVNC_PUBLIC_HTTP_SCHEME", "http")
# Path segment websockify listens on (noVNC default token name).
NOVNC_WEBSOCKET_PATH = os.getenv("NOVNC_WEBSOCKET_PATH", "websockify")


def _normalize_ws_path(path: str) -> str:
    p = path.strip()
    if not p.startswith("/"):
        p = f"/{p}"
    return p


def _path_for_vnc_query(path: str) -> str:
    """Strip leading slashes for vnc.html ?path= token."""
    return path.strip().lstrip("/")


def build_session_vnc_info(session_id: int, vnc_port: int) -> SessionVncInfo:
    host = NOVNC_PUBLIC_HOST
    ws_path = _normalize_ws_path(NOVNC_WEBSOCKET_PATH)
    ws_scheme = NOVNC_PUBLIC_WS_SCHEME
    http_scheme = NOVNC_PUBLIC_HTTP_SCHEME
    path_q = _path_for_vnc_query(NOVNC_WEBSOCKET_PATH)

    websocket_url = f"{ws_scheme}://{host}:{vnc_port}{ws_path}"
    query = "autoconnect=1&resize=scale&reconnect=1" f"&path={quote(path_q, safe='')}"
    http_url = f"{http_scheme}://{host}:{vnc_port}/vnc.html?{query}"

    return SessionVncInfo(
        session_id=session_id,
        websocket_url=websocket_url,
        http_url=http_url,
    )
