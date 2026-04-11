"""Optional HTTP diagnostics (enable with COMPUTER_USE_DEBUG_AGENT_PROBE=1)."""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException

from ..agent_relay import diagnose_agent_openapi_port

router = APIRouter(tags=["debug"])


@router.get("/debug/agent-probe/{port}")
def agent_openapi_probe_report(port: int) -> dict:
    """
    Returns the same structured probe as logged on the server (headers, body preview, curl hint).

    Enable with: COMPUTER_USE_DEBUG_AGENT_PROBE=1
    """
    if os.getenv("COMPUTER_USE_DEBUG_AGENT_PROBE", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        raise HTTPException(
            status_code=404,
            detail="Set COMPUTER_USE_DEBUG_AGENT_PROBE=1 and restart the API.",
        )
    ok, msg, details = diagnose_agent_openapi_port(port)
    return {"ok": ok, "message": msg, "details": details}
