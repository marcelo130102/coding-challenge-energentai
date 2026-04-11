"""Wait for the in-container FastAPI agent (uvicorn) before opening a WebSocket relay."""

from __future__ import annotations

import asyncio
import gzip
import http.client
import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger(__name__)

AGENT_HTTP_WAIT_S = 120.0
AGENT_HTTP_POLL_S = 1.5
AGENT_WS_RETRIES = 25
AGENT_WS_RETRY_DELAY_S = 1.2

_BODY_PREVIEW_LOG_LEN = int(os.getenv("AGENT_PROBE_BODY_LOG_LEN", "4000"))


def _maybe_decompress_body(body: bytes, content_encoding: str) -> bytes:
    enc = (content_encoding or "").lower().strip()
    if not body:
        return body
    if enc == "gzip":
        try:
            return gzip.decompress(body)
        except OSError:
            return body
    if enc == "br":
        try:
            import brotli

            return brotli.decompress(body)
        except ImportError:
            logger.warning(
                "Content-Encoding: br but brotli is not installed; "
                "pip install brotli or the probe may fail.",
            )
        except Exception:
            pass
        return body
    return body


def _preview_text(data: bytes, max_len: int) -> str:
    chunk = data[:max_len]
    text = chunk.decode("utf-8", errors="replace")
    if len(data) > max_len:
        text += f"\n... [truncated, total {len(data)} bytes]"
    return text


def diagnose_agent_openapi_port(port: int) -> tuple[bool, str, dict[str, Any]]:
    """
    GET http://127.0.0.1:{port}/openapi.json and return (ok, user_message, details).

    ``details`` is safe for JSON logging and for GET /api/debug/agent-probe/{port}.
    """
    details: dict[str, Any] = {
        "probe_url": f"http://127.0.0.1:{port}/openapi.json",
        "curl": f"curl -sS -D - 'http://127.0.0.1:{port}/openapi.json' | head -c {_BODY_PREVIEW_LOG_LEN}",
    }
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        conn.request(
            "GET",
            "/openapi.json",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
            },
        )
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()

        details["http_status"] = resp.status
        details["response_headers"] = {k: v for k, v in resp.getheaders()}
        details["raw_byte_len"] = len(raw)
        details["content_encoding"] = resp.getheader("Content-Encoding")

        if resp.status == 404:
            msg = (
                "The remote assistant isn’t running the expected service on this port. "
                "Use the Computer Use demo environment and try again."
            )
            details["body_preview"] = _preview_text(raw, _BODY_PREVIEW_LOG_LEN)
            return False, msg, details

        if resp.status != 200:
            msg = "The remote assistant didn’t respond as expected. Please try again."
            details["body_preview"] = _preview_text(raw, _BODY_PREVIEW_LOG_LEN)
            return False, msg, details

        body = _maybe_decompress_body(raw, resp.getheader("Content-Encoding") or "")
        if body.startswith(b"\xef\xbb\xbf"):
            body = body[3:]
        details["body_byte_len"] = len(body)
        details["body_preview"] = _preview_text(body, _BODY_PREVIEW_LOG_LEN)

        try:
            text = body.decode("utf-8")
            data = json.loads(text)
        except UnicodeDecodeError:
            msg = "The remote assistant didn’t respond as expected. Please try again."
            return False, msg, details
        except json.JSONDecodeError as e:
            preview = body[:400].decode("utf-8", errors="replace")
            srv = (details.get("response_headers") or {}).get("Server", "")
            if preview.lstrip().startswith("<"):
                details["json_parse_error"] = str(e)
                low = preview.lower()
                if "streamlit" in low or "<title>streamlit</title>" in low:
                    details["detected"] = "streamlit"
                    details["stop_polling"] = True
                    msg = (
                        "The remote session is running a different app on this port. "
                        "Use the Computer Use demo container image and try again."
                    )
                elif "tornado" in srv.lower():
                    details["detected"] = "tornado_html"
                    details["stop_polling"] = True
                    msg = (
                        "The remote assistant returned an unexpected page. "
                        "Use the Computer Use demo environment and try again."
                    )
                else:
                    msg = (
                        "The remote assistant returned an unexpected page. "
                        "Please try again with the demo environment."
                    )
            else:
                msg = "The remote assistant didn’t respond as expected. Please try again."
                details["json_parse_error"] = str(e)
            return False, msg, details

        details["parsed_top_level_keys"] = (
            list(data.keys()) if isinstance(data, dict) else type(data).__name__
        )

        if isinstance(data, dict) and (
            "openapi" in data or "swagger" in data or "paths" in data
        ):
            return True, "", details

        msg = "The remote assistant didn’t respond as expected. Please try again."
        return False, msg, details

    except OSError as e:
        msg = "Waiting for the remote assistant…"
        details["os_error"] = repr(e)
        return False, msg, details
    except Exception as e:
        msg = "The remote assistant couldn’t be reached. Please try again."
        details["exception"] = repr(e)
        return False, msg, details


async def wait_for_fastapi_agent_http(port: int) -> tuple[bool, str]:
    """Poll until FastAPI answers or timeout."""
    deadline = time.monotonic() + AGENT_HTTP_WAIT_S
    last_hint = ""
    while time.monotonic() < deadline:
        ok, msg, details = await asyncio.to_thread(diagnose_agent_openapi_port, port)
        last_hint = msg
        if ok:
            return True, ""
        if details.get("stop_polling"):
            logger.error(
                "agent OpenAPI probe abort (will not fix itself by waiting): %s",
                msg,
            )
            return False, msg
        await asyncio.sleep(AGENT_HTTP_POLL_S)
    logger.error(
        "agent OpenAPI probe timed out after %s s (last_error=%r)",
        AGENT_HTTP_WAIT_S,
        last_hint,
    )
    return False, last_hint or "The remote assistant took too long to respond. Please try again."


async def connect_agent_websocket(
    uri: str,
    *,
    websockets_module: Any,
) -> Any:
    last_exc: BaseException | None = None
    for _attempt in range(AGENT_WS_RETRIES):
        try:
            return await websockets_module.connect(
                uri,
                max_size=None,
                open_timeout=30,
            )
        except Exception as e:
            last_exc = e
            await asyncio.sleep(AGENT_WS_RETRY_DELAY_S)
    assert last_exc is not None
    raise last_exc
