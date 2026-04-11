"""
FastAPI WebSocket entrypoint for the Anthropic computer-use agent (runs inside the Docker VM).

Replaces Streamlit for API-driven sessions: tools (computer, bash, edit) execute here where
DISPLAY and the desktop match noVNC.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Coroutine
from typing import Any, cast

from anthropic.types.beta import BetaMessageParam, BetaTextBlockParam
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from computer_use_demo.loop import APIProvider, sampling_loop
from computer_use_demo.tools import ToolResult, ToolVersion

logger = logging.getLogger(__name__)

app = FastAPI(title="Computer Use Agent", version="1.0.0")

DEFAULT_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")
DEFAULT_TOOL_VERSION: ToolVersion = cast(
    ToolVersion,
    os.getenv("ANTHROPIC_TOOL_VERSION", "computer_use_20250429"),
)


def _schedule(coro: Coroutine[Any, Any, Any]) -> None:
    try:
        asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        pass


@app.websocket("/ws")
async def agent_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    messages: list[BetaMessageParam] = []
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    def output_callback(block: Any) -> None:
        if not isinstance(block, dict):
            return
        btype = block.get("type")
        if btype == "text":
            text = (block.get("text") or "").strip()
            if text:
                _schedule(
                    websocket.send_json({"type": "progress", "content": text}),
                )
        elif btype == "tool_use":
            name = block.get("name", "?")
            _schedule(
                websocket.send_json(
                    {"type": "progress", "content": f"Calling tool: {name}"},
                ),
            )
        elif btype == "thinking":
            _schedule(
                websocket.send_json(
                    {"type": "progress", "content": "(thinking…)"},
                ),
            )

    def tool_output_callback(result: ToolResult, tool_use_id: str) -> None:
        preview = (result.output or result.error or "")[:400]
        suffix = "…" if len(preview) == 400 else ""
        _schedule(
            websocket.send_json(
                {
                    "type": "progress",
                    "content": f"Tool result [{tool_use_id[:8]}]: {preview}{suffix}",
                },
            ),
        )

    def api_response_callback(
        _req: object,
        _resp: object | None,
        err: Exception | None,
    ) -> None:
        if err is not None:
            _schedule(
                websocket.send_json(
                    {"type": "progress", "content": f"API error: {err}"},
                ),
            )

    only_n = os.getenv("ANTHROPIC_ONLY_N_IMAGES", "").strip()
    tb_env = os.getenv("ANTHROPIC_THINKING_BUDGET", "").strip()
    max_tok = os.getenv("ANTHROPIC_MAX_TOKENS", "4096")

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
        if not api_key:
            await websocket.send_json(
                {
                    "type": "progress",
                    "content": "Missing ANTHROPIC_API_KEY in the container environment.",
                },
            )
            continue

        messages.append(
            {
                "role": "user",
                "content": [BetaTextBlockParam(type="text", text=content)],
            },
        )
        try:
            messages = await sampling_loop(
                model=DEFAULT_MODEL,
                provider=APIProvider.ANTHROPIC,
                system_prompt_suffix=os.getenv("AGENT_SYSTEM_PROMPT_SUFFIX", ""),
                messages=messages,
                output_callback=output_callback,
                tool_output_callback=tool_output_callback,
                api_response_callback=api_response_callback,
                api_key=api_key,
                only_n_most_recent_images=int(only_n) if only_n else None,
                tool_version=DEFAULT_TOOL_VERSION,
                max_tokens=int(max_tok),
                thinking_budget=int(tb_env) if tb_env else None,
                token_efficient_tools_beta=os.getenv(
                    "TOKEN_EFFICIENT_TOOLS",
                    "",
                ).lower()
                in ("1", "true", "yes"),
            )
        except Exception as e:
            logger.exception("sampling_loop failed")
            await websocket.send_json(
                {"type": "progress", "content": f"Agent error: {e}"},
            )
