"""任务路由：SSE 进度推送 + 状态快照。"""
from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from app.store.db import get_conn
from app.events.bus import event_bus

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.get("/{task_id}/events")
async def task_events(task_id: str):
    conn = get_conn()
    row = conn.execute("SELECT task_id, state FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})

    async def generator():
        async for ev in event_bus.subscribe(task_id):
            event_name = ev.get("event", "message")
            data = json.dumps(ev.get("data", {}), ensure_ascii=False)
            yield f"event: {event_name}\ndata: {data}\n\n"

    return StreamingResponse(generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{task_id}")
def get_task(task_id: str):
    conn = get_conn()
    row = conn.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    conn.close()
    if not row:
        raise HTTPException(404, detail={"code": "TASK_NOT_FOUND", "message": "任务不存在"})
    return {
        "task_id": row["task_id"],
        "document_id": row["document_id"],
        "state": row["state"],
        "progress_pct": row["progress_pct"],
        "current_stage": row["current_stage"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error_message": row["error_message"],
        "events": json.loads(row["events_json"] or "[]"),
    }
