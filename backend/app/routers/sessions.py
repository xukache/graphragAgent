"""会话与问答路由。"""
from __future__ import annotations
import json
import time
import uuid
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.store.db import get_conn
from app.store.files import kg_json_path
from app.schemas.session import (
    SessionCreate, SessionPatch, SessionOut, SessionListOut,
    MessageCreate, MessageOut, MessageListOut,
)
from app.agent_runner.cache import agent_runner
from app.config import SESSION_HISTORY_LIMIT

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


def _ts() -> int:
    return int(time.time() * 1000)


@router.post("", status_code=201, response_model=SessionOut)
def create_session(body: SessionCreate):
    conn = get_conn()
    doc = conn.execute("SELECT status FROM documents WHERE document_id=?", (body.document_id,)).fetchone()
    if not doc:
        conn.close()
        raise HTTPException(404, detail={"code": "DOCUMENT_NOT_FOUND", "message": "文档不存在"})
    if doc["status"] != "ready":
        conn.close()
        raise HTTPException(409, detail={"code": "DOCUMENT_NOT_READY", "message": "文档尚未就绪"})
    sid = str(uuid.uuid4())
    now = _ts()
    conn.execute(
        "INSERT INTO sessions VALUES (?,?,?,?,?,?)",
        (sid, body.document_id, body.title, now, now, 0),
    )
    conn.commit()
    conn.close()
    return SessionOut(session_id=sid, document_id=body.document_id,
                      title=body.title, created_at=now, updated_at=now, message_count=0)


@router.get("", response_model=SessionListOut)
def list_sessions(
    document_id: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM sessions WHERE document_id=?", (document_id,)).fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM sessions WHERE document_id=? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
        (document_id, page_size, (page - 1) * page_size),
    ).fetchall()
    conn.close()
    items = [SessionOut(session_id=r["session_id"], document_id=r["document_id"],
                        title=r["title"], created_at=r["created_at"],
                        updated_at=r["updated_at"], message_count=r["message_count"]) for r in rows]
    return SessionListOut(items=items, total=total, page=page, page_size=page_size)


@router.delete("/{session_id}", status_code=204)
def delete_session(session_id: str):
    conn = get_conn()
    row = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    conn.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
    conn.commit()
    conn.close()


@router.patch("/{session_id}", response_model=SessionOut)
def patch_session(session_id: str, body: SessionPatch):
    """局部更新会话（目前只支持 title）。"""
    conn = get_conn()
    row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    if body.title is None:
        conn.close()
        raise HTTPException(400, detail={"code": "NO_FIELD", "message": "未提供可更新字段"})
    title = body.title.strip() or None
    now = _ts()
    conn.execute(
        "UPDATE sessions SET title=?, updated_at=? WHERE session_id=?",
        (title, now, session_id),
    )
    conn.commit()
    # 重新读取以返回完整字段
    row = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    conn.close()
    return SessionOut(
        session_id=row["session_id"], document_id=row["document_id"],
        title=row["title"], created_at=row["created_at"],
        updated_at=row["updated_at"], message_count=row["message_count"],
    )


@router.delete("/{session_id}/messages", status_code=204)
def clear_session_messages(session_id: str):
    """清空会话内的所有消息，保留会话本身（消息计数归零）。"""
    conn = get_conn()
    row = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not row:
        conn.close()
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
    conn.execute(
        "UPDATE sessions SET message_count=0, updated_at=? WHERE session_id=?",
        (_ts(), session_id),
    )
    conn.commit()
    conn.close()


@router.post("/{session_id}/messages")
async def send_message(session_id: str, body: MessageCreate):
    conn = get_conn()
    sess = conn.execute("SELECT * FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not sess:
        conn.close()
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    doc_id = sess["document_id"]

    history = conn.execute(
        "SELECT role, content FROM messages WHERE session_id=? ORDER BY created_at LIMIT ?",
        (session_id, SESSION_HISTORY_LIMIT),
    ).fetchall()
    conn.close()

    msgs = [{"role": r["role"], "content": r["content"]} for r in history]
    msgs.append({"role": "user", "content": body.content})

    # 保存 user 消息
    user_mid = str(uuid.uuid4())
    now = _ts()
    conn2 = get_conn()
    conn2.execute(
        "INSERT INTO messages(message_id,session_id,role,content,created_at) VALUES (?,?,?,?,?)",
        (user_mid, session_id, "user", body.content, now),
    )
    conn2.execute("UPDATE sessions SET updated_at=?, message_count=message_count+1 WHERE session_id=?",
                  (now, session_id))
    conn2.commit()
    conn2.close()

    # 调用 Agent
    kg_path = kg_json_path(doc_id)
    try:
        store, agent = agent_runner.get_or_load(doc_id, kg_path)
    except Exception as e:
        raise HTTPException(500, detail={"code": "LLM_ERROR", "message": str(e)})

    if body.stream:
        async def stream_gen():
            answer_parts = []
            tool_calls = []
            seen_tool_sigs = set()
            # tool_call_chunks 累积器（按 index 跟踪 args 字符串）。
            # LangGraph v2 流式下，token.tool_calls 始终是 {}（仅在流结束后才完整），
            # 完整 args 只在 tool_call_chunks 里逐 token 累积。
            tc_buf: dict[int, dict] = {}
            pending_sse: list[str] = []  # 当前 chunk 内待发出的 SSE 行
            t0 = time.time()

            def flush_tc(idx: int) -> None:
                """把 tc_buf[idx] 的累积结果 parse 为 dict，加入 tool_calls 与 SSE 队列。"""
                buf = tc_buf.pop(idx, None)
                if not buf or not buf.get("name"):
                    return
                raw_args = buf.get("args", "") or ""
                try:
                    parsed_args = json.loads(raw_args) if raw_args.strip() else {}
                except json.JSONDecodeError:
                    parsed_args = {"_raw": raw_args}
                sig = f"{buf['name']}:{json.dumps(parsed_args, ensure_ascii=False, sort_keys=True)}"
                if sig in seen_tool_sigs:
                    return
                seen_tool_sigs.add(sig)
                tool_calls.append({"name": buf["name"], "args": parsed_args})
                data = json.dumps({"name": buf["name"], "args": parsed_args}, ensure_ascii=False)
                pending_sse.append(f"event: tool_call\ndata: {data}\n\n")

            try:
                # stream_mode="messages" + version="v2" 是官方推荐的逐 token 流式方式。
                # version="v2" 使用统一的 StreamPart 格式：chunk["type"] == "messages"
                # chunk["data"] == (message_chunk, metadata)
                # 参考：https://docs.langchain.com/oss/python/langgraph/streaming
                async for chunk in agent.astream(
                    {"messages": msgs},
                    stream_mode="messages",
                    version="v2",
                ):
                    if chunk.get("type") != "messages":
                        continue
                    token, metadata = chunk["data"]
                    msg_type = getattr(token, "type", None)

                    # 工具调用：从 tool_call_chunks 累积 args 字符串
                    tc_chunks = getattr(token, "tool_call_chunks", None) or []
                    if tc_chunks:
                        for tc in tc_chunks:
                            idx = tc.get("index", 0)
                            if tc.get("name"):
                                # 新 name chunk：先 flush 任何非当前 idx 的旧 buffer
                                for prev_idx in [k for k in tc_buf.keys() if k != idx]:
                                    flush_tc(prev_idx)
                                tc_buf[idx] = {
                                    "name": tc["name"],
                                    "args": tc.get("args") or "",
                                    "id": tc.get("id"),
                                }
                            else:
                                # 续传 args 字符串片段
                                if idx in tc_buf:
                                    tc_buf[idx]["args"] += tc.get("args") or ""

                    # 文本 token：只取 AI 消息 chunk 的增量内容（type 为 AIMessageChunk）
                    if msg_type == "AIMessageChunk":
                        content = getattr(token, "content", None)
                        if content:
                            # content 可能是 str 或 list（多模态）；统一成文本
                            if isinstance(content, list):
                                text = "".join(
                                    part.get("text", "") if isinstance(part, dict) else str(part)
                                    for part in content
                                )
                            else:
                                text = content
                            if text:
                                answer_parts.append(text)
                                pending_sse.append(
                                    f"event: token\ndata: {json.dumps({'text': text}, ensure_ascii=False)}\n\n"
                                )

                    # 本 chunk 处理完，先把所有待发的 SSE 行发出
                    for line in pending_sse:
                        yield line
                    pending_sse.clear()
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"
                return

            # 流结束：flush 所有未发出的 tool_call（最后一段 args 可能还在 tc_buf 里）
            for prev_idx in list(tc_buf.keys()):
                flush_tc(prev_idx)
            for line in pending_sse:
                yield line
            pending_sse.clear()

            answer = "".join(answer_parts)
            latency = int((time.time() - t0) * 1000)
            mid = str(uuid.uuid4())
            ts = _ts()

            # 从工具调用参数和回答文本中提取 entity_id（用于前端 KG 高亮）
            import re as _re
            entity_ids: list[str] = []
            seen_eids: set[str] = set()
            for tc in tool_calls:
                eid = tc.get("args", {}).get("entity_id")
                if eid and eid not in seen_eids:
                    entity_ids.append(eid)
                    seen_eids.add(eid)
            # 从回答文本里扫 e_xxxxxxxx 格式的 entity_id
            for eid in _re.findall(r'\be_[0-9a-f]{8}\b', answer):
                if eid not in seen_eids:
                    entity_ids.append(eid)
                    seen_eids.add(eid)

            c3 = get_conn()
            c3.execute(
                "INSERT INTO messages(message_id,session_id,role,content,tool_calls_json,created_at,latency_ms) VALUES (?,?,?,?,?,?,?)",
                (mid, session_id, "assistant", answer, json.dumps(tool_calls), ts, latency),
            )
            c3.execute("UPDATE sessions SET updated_at=?, message_count=message_count+1 WHERE session_id=?",
                       (ts, session_id))
            c3.commit()
            c3.close()
            complete = {"message_id": mid, "answer": answer, "tool_calls": tool_calls,
                        "tool_call_count": len(tool_calls), "latency_ms": latency,
                        "entity_ids": entity_ids, "ts": ts}
            yield f"event: complete\ndata: {json.dumps(complete, ensure_ascii=False)}\n\n"

        return StreamingResponse(stream_gen(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no",
                                          "Connection": "keep-alive"})
    else:
        from graphrag_pipeline.agent import ask
        t0 = time.time()
        result = ask(agent, body.content)
        latency = int((time.time() - t0) * 1000)
        mid = str(uuid.uuid4())
        ts = _ts()
        c3 = get_conn()
        c3.execute(
            "INSERT INTO messages(message_id,session_id,role,content,tool_calls_json,created_at,latency_ms) VALUES (?,?,?,?,?,?,?)",
            (mid, session_id, "assistant", result["answer"], json.dumps(result.get("tool_calls", [])), ts, latency),
        )
        c3.execute("UPDATE sessions SET updated_at=?, message_count=message_count+1 WHERE session_id=?",
                   (ts, session_id))
        c3.commit()
        c3.close()
        return {
            "message_id": mid, "session_id": session_id,
            "question": body.content, "answer": result["answer"],
            "tool_calls": result.get("tool_calls", []),
            "tool_call_count": result.get("tool_call_count", 0),
            "latency_ms": latency, "created_at": ts,
        }


@router.get("/{session_id}/messages", response_model=MessageListOut)
def get_messages(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    conn = get_conn()
    sess = conn.execute("SELECT session_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    if not sess:
        conn.close()
        raise HTTPException(404, detail={"code": "SESSION_NOT_FOUND", "message": "会话不存在"})
    total = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id=?", (session_id,)).fetchone()[0]
    rows = conn.execute(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at LIMIT ? OFFSET ?",
        (session_id, page_size, (page - 1) * page_size),
    ).fetchall()
    conn.close()
    items = []
    for r in rows:
        tc = json.loads(r["tool_calls_json"]) if r["tool_calls_json"] else []
        items.append(MessageOut(
            message_id=r["message_id"], session_id=r["session_id"],
            role=r["role"], content=r["content"],
            tool_calls=tc, tool_call_count=len(tc),
            latency_ms=r["latency_ms"], created_at=r["created_at"],
        ))
    return MessageListOut(items=items, total=total, page=page, page_size=page_size)
