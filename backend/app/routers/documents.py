"""文档管理路由：上传 / 列表 / 详情 / KG / 删除。"""
from __future__ import annotations
import asyncio
import json
import mimetypes
import re
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, File

from app.config import DOCUMENTS_DIR
from app.store.db import get_conn
from app.store.files import (
    ensure_doc_dirs, source_path, kg_json_path, delete_doc_dir, content_list_path, page_id_prefix,
)
from app.schemas.document import (
    DocumentOut, DocumentListOut, UploadOut, KGStats, TaskSummary, DocumentPagesOut,
)
from app.agent_runner.cache import agent_runner
from app.orchestrator.job import run_index_job

router = APIRouter(prefix="/api/documents", tags=["documents"])

SUPPORTED_EXTS = {
    "pdf", "doc", "docx", "ppt", "pptx", "xls", "xlsx",
    "png", "jpg", "jpeg", "bmp", "webp", "html",
}
MAX_SIZE = 200 * 1024 * 1024  # 200MB


def _ts() -> int:
    return int(time.time() * 1000)


def _row_to_doc(row) -> DocumentOut:
    kg_stats = None
    if row["kg_stats_json"]:
        try:
            s = json.loads(row["kg_stats_json"])
            kg_stats = KGStats(**s)
        except Exception:
            pass
    return DocumentOut(
        document_id=row["document_id"],
        original_filename=row["original_filename"],
        file_size_bytes=row["file_size_bytes"],
        mime_type=row["mime_type"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        error_message=row["error_message"],
        kg_stats=kg_stats,
    )


async def _update_task(task_id: str, state: str, progress_pct: int = 0,
                       current_stage: str = "", error_message: str | None = None) -> None:
    conn = get_conn()
    now = _ts()
    finished = now if state in ("done", "failed") else None
    conn.execute(
        "UPDATE tasks SET state=?, progress_pct=?, current_stage=?, "
        "error_message=?, finished_at=? WHERE task_id=?",
        (state, progress_pct, current_stage, error_message, finished, task_id),
    )
    conn.commit()
    conn.close()


async def _update_doc(document_id: str, status: str,
                      kg_stats=None, error_message: str | None = None) -> None:
    conn = get_conn()
    kg_json = json.dumps(kg_stats) if kg_stats else None
    conn.execute(
        "UPDATE documents SET status=?, kg_stats_json=?, error_message=?, updated_at=? WHERE document_id=?",
        (status, kg_json, error_message, _ts(), document_id),
    )
    conn.commit()
    conn.close()


@router.post("", status_code=201, response_model=UploadOut)
async def upload_document(file: UploadFile = File(...)):
    filename = file.filename or "upload"
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(400, detail={"code": "UNSUPPORTED_FILE_TYPE", "message": f"不支持 .{ext}"})

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, detail={"code": "FILE_TOO_LARGE", "message": "文件超过 200MB"})

    doc_id = str(uuid.uuid4())
    task_id = str(uuid.uuid4())
    now = _ts()
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"

    ensure_doc_dirs(doc_id)
    src = source_path(doc_id, ext)
    src.write_bytes(content)

    conn = get_conn()
    conn.execute(
        "INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?)",
        (doc_id, filename, len(content), mime, "pending", now, now, None, None),
    )
    conn.execute(
        "INSERT INTO tasks(task_id,document_id,state,progress_pct,current_stage,started_at,events_json) VALUES (?,?,?,?,?,?,?)",
        (task_id, doc_id, "queued", 0, "queued", now, "[]"),
    )
    conn.commit()
    conn.close()

    asyncio.create_task(run_index_job(task_id, doc_id, src, _update_task, _update_doc))

    return UploadOut(
        document_id=doc_id,
        task_id=task_id,
        original_filename=filename,
        file_size_bytes=len(content),
        status="pending",
        created_at=now,
        events_url=f"/api/tasks/{task_id}/events",
    )


@router.get("", response_model=DocumentListOut)
def list_documents(
    status: str | None = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    sort: str = Query("created_at_desc"),
):
    conn = get_conn()
    where = "WHERE status=?" if status else ""
    params = [status] if status else []
    order = "created_at DESC" if "desc" in sort else "created_at ASC"
    total = conn.execute(f"SELECT COUNT(*) FROM documents {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT * FROM documents {where} ORDER BY {order} LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    ).fetchall()
    conn.close()
    return DocumentListOut(
        items=[_row_to_doc(r) for r in rows],
        total=total, page=page, page_size=page_size,
    )


@router.get("/{document_id}", response_model=DocumentOut)
def get_document(document_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM documents WHERE document_id=?", (document_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "文档不存在"})
    task = conn.execute(
        "SELECT task_id, state, progress_pct FROM tasks WHERE document_id=? ORDER BY rowid DESC LIMIT 1",
        (document_id,),
    ).fetchone()
    conn.close()
    doc = _row_to_doc(row)
    if task:
        doc.current_task = TaskSummary(task_id=task["task_id"], state=task["state"], progress_pct=task["progress_pct"])
    return doc


@router.get("/{document_id}/kg")
def get_kg(document_id: str):
    conn = get_conn()
    row = conn.execute("SELECT status FROM documents WHERE document_id=?", (document_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "文档不存在"})
    if row["status"] != "ready":
        raise HTTPException(409, detail={"code": "DOCUMENT_NOT_READY", "message": "文档尚未索引完成"})
    path = kg_json_path(document_id)
    if not path.exists():
        raise HTTPException(404, detail={"code": "KG_NOT_FOUND", "message": "KG 文件不存在"})
    return json.loads(path.read_text())


_HTML_TAG_RE = re.compile(r"<[^>]+>")


@router.get("/{document_id}/pages", response_model=DocumentPagesOut)
def get_document_pages(document_id: str):
    """返回按 page_idx 分组的纯文本，page_id 格式：{prefix}_page_{idx}。

    prefix 来自 task_meta.json 的 file_name（与 langextract converter
    生成 KG sources[].document_id 的约定保持一致，通常为 "source.pdf"）。
    文档不存在 → 404；mineru 产物缺失或解析失败 → 200 + `{"pages": {}}`。
    """
    conn = get_conn()
    row = conn.execute("SELECT document_id FROM documents WHERE document_id=?", (document_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "文档不存在"})

    cl_path = content_list_path(document_id)
    if not cl_path:
        return DocumentPagesOut(pages={})

    try:
        blocks = json.loads(cl_path.read_text(encoding="utf-8"))
    except Exception:
        return DocumentPagesOut(pages={})

    prefix = page_id_prefix(document_id)

    grouped: dict[int, list[str]] = {}
    for block in blocks:
        btype = block.get("type")
        if btype == "text":
            text = block.get("text", "") or ""
        elif btype == "table":
            text = _HTML_TAG_RE.sub(" ", block.get("table_body", "") or "")
        else:
            continue

        page_idx = block.get("page_idx")
        if page_idx is None:
            continue
        text = text.strip()
        if not text:
            continue
        grouped.setdefault(page_idx, []).append(text)

    return DocumentPagesOut(pages={
        f"{prefix}_page_{idx}": "\n\n".join(chunks)
        for idx, chunks in sorted(grouped.items())
    })


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: str):
    conn = get_conn()
    row = conn.execute("SELECT document_id FROM documents WHERE document_id=?", (document_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "文档不存在"})
    conn.execute("DELETE FROM documents WHERE document_id=?", (document_id,))
    conn.commit()
    conn.close()
    agent_runner.evict(document_id)
    delete_doc_dir(document_id)
