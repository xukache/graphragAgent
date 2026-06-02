"""健康检查路由。"""
from __future__ import annotations
import time
from pathlib import Path
from fastapi import APIRouter
from app.config import MINERU_VENV_PYTHON, LANGEXTRACT_VENV_PYTHON, QWEN_API_KEY, BASE_DIR

router = APIRouter(prefix="/api", tags=["health"])
_start_time = time.time()


@router.get("/health")
def health():
    checks = {}

    # SQLite
    try:
        from app.store.db import get_conn
        conn = get_conn()
        conn.execute("SELECT 1")
        conn.close()
        checks["sqlite"] = "ok"
    except Exception as e:
        checks["sqlite"] = str(e)

    # data_dir
    from app.config import DATA_DIR
    checks["data_dir"] = "ok" if DATA_DIR.exists() else "missing"

    # subprocess venvs
    import os as _os
    for name, py_path in [("mineru_subprocess", MINERU_VENV_PYTHON),
                           ("langextract_subprocess", LANGEXTRACT_VENV_PYTHON)]:
        if not py_path:
            checks[name] = "not_configured"
        else:
            # .env 中的相对路径以 backend/ 为基准。用 abspath 规范化（不跟随软链，
            # 与 orchestrator 保持一致：venv python 多为指向 base python 的软链）。
            resolved = _os.path.abspath(_os.path.join(str(BASE_DIR), py_path))
            checks[name] = "ok" if _os.path.exists(resolved) else f"missing: {resolved}"

    # LLM config
    checks["qwen_llm"] = "ok" if QWEN_API_KEY else "missing_api_key"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {
        "status": overall,
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _start_time),
        "checks": checks,
    }
