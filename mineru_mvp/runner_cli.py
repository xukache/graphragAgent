"""Backend orchestrator 调用入口：薄封装 mineru_pipeline.run_pipeline()。

由 backend/app/orchestrator/job.py 用 `python -m mineru_mvp.runner_cli` 启动。
保持原有 `mineru_pipeline.py` 的 MVP 调用方式不变。

接受参数：
  --input      原始文档绝对路径（必填）
  --output-dir 解析结果输出目录（必填，文件直接落到该目录，不再嵌套 output/）

可选向 PROGRESS_FD 推 JSON 进度事件（环境变量由 orchestrator 注入）。
当 PROGRESS_FD 不存在时，所有事件被静默丢弃，pipeline 仍能正常跑完。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 让 `python -m mineru_mvp.runner_cli` 在任意 cwd 下都能找到 mineru_pipeline 模块
_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR.parent))

from mineru_mvp.mineru_pipeline import run_pipeline  # noqa: E402


def _emit(ev: dict) -> None:
    """把进度事件写到 PROGRESS_FD（orchestrator 监听）。无 fd 时丢弃。"""
    fd_str = os.environ.get("PROGRESS_FD")
    if not fd_str:
        return
    try:
        fd = int(fd_str)
        line = (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8")
        os.write(fd, line)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="MinerU 解析 runner（backend orchestrator 入口）")
    parser.add_argument("--input", required=True, type=Path, help="原始文档绝对路径")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="解析结果输出目录（文件直接落盘到此）")
    args = parser.parse_args()

    src = args.input.resolve()
    out_dir = args.output_dir.resolve()

    if not src.exists():
        _emit({"type": "error", "message": f"输入文件不存在: {src}"})
        print(f"❌ 输入文件不存在: {src}", file=sys.stderr)
        return 1

    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    _emit({"type": "progress", "pct": 5, "detail": "开始上传到 MinerU"})

    try:
        run_pipeline(src, out_dir)
    except Exception as exc:
        _emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        # 让 stderr 也带详细信息（落到 logs/parsing.stderr.log）
        import traceback
        traceback.print_exc()
        return 1

    elapsed_ms = int((time.time() - t0) * 1000)
    _emit({"type": "progress", "pct": 100, "detail": "MinerU 解析完成"})
    _emit({"type": "stage_done", "elapsed_ms": elapsed_ms})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
