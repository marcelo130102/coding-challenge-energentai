from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, field_validator


class SessionCreate(BaseModel):
    status: str = Field(..., max_length=64)
    api_key: SecretStr = Field(
        ...,
        json_schema_extra={"format": "password"},
        description="Anthropic API key for this session (never returned on GET).",
    )
    api_endpoint: Literal["global", "packyapi"] = Field(
        default="global",
        description="Global Anthropic API vs PackyAPI (https://www.packyapi.com).",
    )
    base_url: HttpUrl | None = Field(
        default=None,
        description="Optional override; when set, overrides api_endpoint.",
    )
    vnc_port: int | None = Field(
        default=None,
        description="Ignored when Docker orchestration is enabled; optional for manual/no-Docker mode.",
    )
    agent_api_port: int | None = Field(
        default=None,
        description="Host port for Streamlit when orchestration is disabled.",
    )

    @field_validator("base_url", mode="before")
    @classmethod
    def base_url_must_be_https(cls, v: object) -> object:
        if v is None:
            return None
        s = str(v)
        if not s.startswith("https://"):
            raise ValueError("base_url must use https")
        return v


class SessionRead(BaseModel):
    """Session fields safe to expose over GET (no API keys or base URLs)."""

    model_config = ConfigDict(from_attributes=False)

    id: int
    status: str
    created_at: datetime
    vnc_port: int | None
    agent_api_port: int | None = None
    docker_container_id: str | None = None
    credentials_stored: bool = Field(
        default=False,
        description="True if an API key is stored for this session.",
    )
    api_endpoint: str | None = Field(
        default=None,
        description="global, packyapi, or custom (no URL returned).",
    )


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
