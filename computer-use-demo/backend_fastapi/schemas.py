from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    status: str = Field(..., max_length=64)
    vnc_port: int | None = Field(
        default=None,
        description="Ignored when Docker orchestration is enabled; optional for manual/no-Docker mode.",
    )
    agent_api_port: int | None = Field(
        default=None,
        description="Host port for Streamlit when orchestration is disabled.",
    )


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    vnc_port: int | None
    agent_api_port: int | None = None
    docker_container_id: str | None = None


class MessageCreate(BaseModel):
    session_id: int
    role: str = Field(..., max_length=32)
    content: str


class MessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: str
    content: str
    timestamp: datetime


class SessionWithMessages(SessionRead):
    messages: list[MessageRead] = Field(default_factory=list)


class SessionVncInfo(BaseModel):
    """Public URLs for embedding noVNC (HTTP page + WebSocket path used by websockify)."""

    session_id: int
    websocket_url: str
    http_url: str
