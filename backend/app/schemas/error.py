from __future__ import annotations
from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict | None = None


class ErrorOut(BaseModel):
    error: ErrorDetail
    trace_id: str | None = None
