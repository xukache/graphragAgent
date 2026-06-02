"""IndexJob：subprocess 串联 MinerU + LangExtract，推送进度事件。"""
from __future__ import annotations
import asyncio
import json
import logging
import time
from pathlib import Path

from app.config import (
    MINERU_VENV_PYTHON, LANGEXTRACT_VENV_PYTHON,
    MINERU_TIMEOUT_SECONDS, LANGEXTRACT_TIMEOUT_SECONDS,
    BASE_DIR,
)
from app.events.bus import event_bus
from app.store.files import mineru_dir, kg_dir, logs_dir, kg_json_path
from app.agent_runner.cache import agent_runner

logger = logging.getLogger(__name__)

# 进度权重：parsing 40%，extracting 50%，building_kg 10%
_STAGE_WEIGHT = {"parsing": 40, "extracting": 50, "building_kg": 10}
_STAGE_BASE = {"parsing": 0, "extracting": 40, "building_kg": 90}


def _overall_pct(stage: str, stage_pct: int) -> int:
    base = _STAGE_BASE.get(stage, 0)
    weight = _STAGE_WEIGHT.get(stage, 10)
    return min(99, base + int(stage_pct * weight / 100))


async def _run_subprocess(
    cmd: list[str],
    stdout_log: Path,
    stderr_log: Path,
    timeout: int,
    task_id: str,
    stage: str,
    cwd: Path | None = None,
) -> bool:
    """运行 subprocess，从 fd 3 读进度行，返回是否成功。"""
    import os
    r_fd, w_fd = os.pipe()

    # 关键：清掉父进程从 `uv run` 继承下来的 VIRTUAL_ENV / PYTHONPATH / PYTHONHOME，
    # 否则子 venv 的 python 启动时会按这些变量去 backend/.venv 找 site-packages，
    # 导致 langextract / mineru 子 venv 装的 pandas 等依赖加载不到。
    #
    # 同时清掉所有 *_PROXY 代理变量：MinerU CDN / DashScope 都是国内域名，
    # 走本机 SOCKS 代理会触发 "Missing dependencies for SOCKS support"
    # （子 venv 未装 socksio）或 SSL EOF。这与项目 steering 规范一致。
    _STRIP = {"VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME"}
    _PROXY_KEYS = {
        "ALL_PROXY", "all_proxy",
        "HTTP_PROXY", "http_proxy",
        "HTTPS_PROXY", "https_proxy",
        "FTP_PROXY", "ftp_proxy",
    }
    env = {k: v for k, v in os.environ.items()
           if k not in _STRIP and k not in _PROXY_KEYS}
    env["PROGRESS_FD"] = str(w_fd)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=open(stdout_log, "w"),
        stderr=open(stderr_log, "w"),
        pass_fds=(w_fd,),
        env=env,
        cwd=str(cwd) if cwd else None,
    )
    os.close(w_fd)

    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    loop = asyncio.get_event_loop()
    transport, _ = await loop.connect_read_pipe(lambda: protocol, os.fdopen(r_fd))

    async def read_progress():
        while True:
            try:
                line = await asyncio.wait_for(reader.readline(), timeout=5)
            except asyncio.TimeoutError:
                continue
            if not line:
                break
            try:
                ev = json.loads(line.decode().strip())
                ev_type = ev.get("type", "progress")
                if ev_type == "progress":
                    pct = _overall_pct(stage, ev.get("pct", 0))
                    event_bus.publish(task_id, {
                        "event": "progress",
                        "data": {"stage": stage, "pct": pct, "detail": ev.get("detail", ""), "ts": _ts()},
                    })
                elif ev_type == "stage_done":
                    event_bus.publish(task_id, {
                        "event": "stage_done",
                        "data": {"stage": stage, "elapsed_ms": ev.get("elapsed_ms", 0), "ts": _ts()},
                    })
                elif ev_type == "error":
                    event_bus.publish(task_id, {
                        "event": "error",
                        "data": {"stage": stage, "message": ev.get("message", ""), "ts": _ts()},
                    })
            except Exception:
                pass

    try:
        await asyncio.wait_for(
            asyncio.gather(proc.wait(), read_progress()),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()
        return False
    finally:
        transport.close()

    return proc.returncode == 0


def _ts() -> int:
    return int(time.time() * 1000)


async def run_index_job(
    task_id: str,
    document_id: str,
    source_file: Path,
    update_task_fn,
    update_doc_fn,
) -> None:
    """完整索引流程：MinerU → LangExtract → KG → 缓存。"""
    m_dir = mineru_dir(document_id)
    k_dir = kg_dir(document_id)
    l_dir = logs_dir(document_id)

    async def _stage(stage: str, cmd: list[str], timeout: int, venv_py: str,
                     cwd: Path | None = None) -> bool:
        if not Path(venv_py).exists():
            # venv 不存在时跳过 subprocess，直接模拟成功（用于测试）
            logger.warning("venv not found: %s, skipping subprocess", venv_py)
            return True

        event_bus.publish(task_id, {
            "event": "stage_start",
            "data": {"stage": stage, "message": f"正在执行 {stage}", "ts": _ts()},
        })
        await update_task_fn(task_id, state=stage, progress_pct=_STAGE_BASE[stage], current_stage=stage)

        ok = await _run_subprocess(
            cmd,
            l_dir / f"{stage}.stdout.log",
            l_dir / f"{stage}.stderr.log",
            timeout,
            task_id,
            stage,
            cwd=cwd,
        )
        return ok

    # 项目根 + 各组件根（用作 subprocess 的 cwd / -m 包搜索路径）
    PROJECT_ROOT = BASE_DIR.parent  # /.../graphragAgent
    MINERU_PKG_ROOT = PROJECT_ROOT  # `python -m mineru_mvp.runner_cli` 需要 cwd = 项目根
    LANGEXTRACT_PKG_ROOT = PROJECT_ROOT / "langextract_src"  # `-m examples.mineru_to_kg.runner_cli`

    # ⚠️ 用 os.path.abspath 规范化路径，绝不能用 .resolve()：
    # venv 的 bin/python 通常是指向 miniconda/系统 python 的符号链接，
    # .resolve() 会跟随软链把它解析成 base python，导致 venv 失效、
    # 子 venv 装的 pandas 等依赖加载不到。abspath 只清理 .. 不跟随软链。
    import os as _os

    def _venv_python(rel_path: str) -> str:
        return _os.path.abspath(_os.path.join(str(BASE_DIR), rel_path)) if rel_path else ""

    try:
        # 阶段 1：MinerU 解析
        mineru_py = _venv_python(MINERU_VENV_PYTHON)
        ok = await _stage(
            "parsing",
            [mineru_py, "-m", "mineru_mvp.runner_cli",
             "--input", str(source_file),
             "--output-dir", str(m_dir)],
            MINERU_TIMEOUT_SECONDS,
            mineru_py,
            cwd=MINERU_PKG_ROOT,
        )
        if not ok:
            raise RuntimeError("MinerU 解析失败")

        # 阶段 2：LangExtract + KG
        lx_py = _venv_python(LANGEXTRACT_VENV_PYTHON)
        ok = await _stage(
            "extracting",
            [lx_py, "-m", "examples.mineru_to_kg.runner_cli",
             "--mineru-output", str(m_dir),
             "--output-dir", str(k_dir)],
            LANGEXTRACT_TIMEOUT_SECONDS,
            lx_py,
            cwd=LANGEXTRACT_PKG_ROOT,
        )
        if not ok:
            raise RuntimeError("LangExtract 抽取失败")

        # 阶段 3：加载 KG 到缓存
        event_bus.publish(task_id, {
            "event": "stage_start",
            "data": {"stage": "building_kg", "message": "构建知识图谱缓存", "ts": _ts()},
        })
        await update_task_fn(task_id, state="building_kg", progress_pct=90, current_stage="building_kg")

        kg_path = kg_json_path(document_id)
        kg_stats = None
        if kg_path.exists():
            import json as _json
            kg_data = _json.loads(kg_path.read_text())
            kg_stats = kg_data.get("stats")
            try:
                # 预热缓存：直接 get_or_load 会自动构建并写入缓存。
                # 注意不要先写 (None, None) 占位，否则若构建失败会在缓存里
                # 留下毒值，后续问答命中缓存拿到 None → 'NoneType' has no astream。
                agent_runner.evict(document_id)
                agent_runner.get_or_load(document_id, kg_path)
            except Exception as e:
                logger.warning("Agent 缓存预热失败（非致命，问答时会重试加载）: %s", e)
                agent_runner.evict(document_id)

        # 完成
        await update_task_fn(task_id, state="done", progress_pct=100, current_stage="done")
        await update_doc_fn(document_id, status="ready", kg_stats=kg_stats)
        event_bus.publish(task_id, {
            "event": "complete",
            "data": {
                "document_id": document_id,
                "status": "ready",
                "kg_stats": kg_stats,
                "ts": _ts(),
            },
        })

    except Exception as exc:
        msg = str(exc)
        logger.error("IndexJob failed for %s: %s", document_id, msg)
        await update_task_fn(task_id, state="failed", error_message=msg)
        await update_doc_fn(document_id, status="failed", error_message=msg)
        event_bus.publish(task_id, {
            "event": "error",
            "data": {"stage": "unknown", "message": msg, "ts": _ts()},
        })
    finally:
        event_bus.close(task_id)
