from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SessionCreate(BaseModel):
    status: str = Field(..., max_length=64)
    vnc_port: int | None = None


class SessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: str
    created_at: datetime
    vnc_port: int | None


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
