"""SQLite 数据库连接与表初始化。"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from app.config import DB_PATH


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    """创建所有表（幂等）。"""
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            document_id   TEXT PRIMARY KEY,
            original_filename TEXT NOT NULL,
            file_size_bytes   INTEGER NOT NULL,
            mime_type         TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'pending',
            created_at        INTEGER NOT NULL,
            updated_at        INTEGER NOT NULL,
            error_message     TEXT,
            kg_stats_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_documents_status_created
            ON documents(status, created_at DESC);

        CREATE TABLE IF NOT EXISTS tasks (
            task_id       TEXT PRIMARY KEY,
            document_id   TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
            state         TEXT NOT NULL DEFAULT 'queued',
            progress_pct  INTEGER NOT NULL DEFAULT 0,
            current_stage TEXT,
            started_at    INTEGER,
            finished_at   INTEGER,
            error_message TEXT,
            events_json   TEXT NOT NULL DEFAULT '[]'
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_document_id ON tasks(document_id);

        CREATE TABLE IF NOT EXISTS sessions (
            session_id    TEXT PRIMARY KEY,
            document_id   TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
            title         TEXT,
            created_at    INTEGER NOT NULL,
            updated_at    INTEGER NOT NULL,
            message_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_sessions_document_updated
            ON sessions(document_id, updated_at DESC);

        CREATE TABLE IF NOT EXISTS messages (
            message_id    TEXT PRIMARY KEY,
            session_id    TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
            role          TEXT NOT NULL,
            content       TEXT NOT NULL,
            tool_calls_json TEXT,
            created_at    INTEGER NOT NULL,
            latency_ms    INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_messages_session_created
            ON messages(session_id, created_at);
    """)
    conn.commit()
    conn.close()
