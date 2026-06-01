from __future__ import annotations
from typing import Any
from pydantic import BaseModel


class KGStats(BaseModel):
    entity_count: int
    triple_count: int
    by_class: dict[str, int]


class TaskSummary(BaseModel):
    task_id: str
    state: str
    progress_pct: int


class DocumentOut(BaseModel):
    document_id: str
    original_filename: str
    file_size_bytes: int
    mime_type: str
    status: str
    created_at: int
    updated_at: int
    error_message: str | None = None
    kg_stats: KGStats | None = None
    current_task: TaskSummary | None = None


class DocumentListOut(BaseModel):
    items: list[DocumentOut]
    total: int
    page: int
    page_size: int


class UploadOut(BaseModel):
    document_id: str
    task_id: str
    original_filename: str
    file_size_bytes: int
    status: str
    created_at: int
    events_url: str


class DocumentPagesOut(BaseModel):
    pages: dict[str, str]
