from __future__ import annotations
from pydantic import BaseModel


class SessionCreate(BaseModel):
    document_id: str
    title: str | None = None


class SessionPatch(BaseModel):
    title: str | None = None


class SessionOut(BaseModel):
    session_id: str
    document_id: str
    title: str | None
    created_at: int
    updated_at: int
    message_count: int


class SessionListOut(BaseModel):
    items: list[SessionOut]
    total: int
    page: int
    page_size: int


class MessageCreate(BaseModel):
    content: str
    stream: bool = True


class MessageOut(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    tool_calls: list[dict] | None = None
    tool_call_count: int = 0
    latency_ms: int | None = None
    created_at: int


class MessageListOut(BaseModel):
    items: list[MessageOut]
    total: int
    page: int
    page_size: int
