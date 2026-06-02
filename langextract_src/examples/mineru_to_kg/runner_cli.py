"""Backend orchestrator 调用入口：薄封装 examples.mineru_to_kg.pipeline.run_pipeline。

由 backend/app/orchestrator/job.py 用
`python -m examples.mineru_to_kg.runner_cli --mineru-output X --output-dir Y` 启动。

进度事件按需写到 PROGRESS_FD（orchestrator 监听）；无 fd 时丢弃。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# 让 `python -m examples.mineru_to_kg.runner_cli` 在 langextract_src/ 之外的 cwd 也能找到包
_PKG_DIR = Path(__file__).resolve().parent  # examples/mineru_to_kg
_LX_ROOT = _PKG_DIR.parent.parent  # langextract_src
if str(_LX_ROOT) not in sys.path:
    sys.path.insert(0, str(_LX_ROOT))

from examples.mineru_to_kg.pipeline import run_pipeline  # noqa: E402


def _emit(ev: dict) -> None:
    fd_str = os.environ.get("PROGRESS_FD")
    if not fd_str:
        return
    try:
        fd = int(fd_str)
        os.write(fd, (json.dumps(ev, ensure_ascii=False) + "\n").encode("utf-8"))
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="LangExtract+KG 抽取 runner（backend orchestrator 入口）"
    )
    parser.add_argument("--mineru-output", required=True, type=Path,
                        help="MinerU 阶段输出目录（含 *content_list.json）")
    parser.add_argument("--output-dir", required=True, type=Path,
                        help="KG 输出目录（knowledge_graph.json 等）")
    args = parser.parse_args()

    mineru_dir = args.mineru_output.resolve()
    out_dir = args.output_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    _emit({"type": "progress", "pct": 5, "detail": "开始 LangExtract 抽取"})

    try:
        run_pipeline(mineru_dir, out_dir)
    except Exception as exc:
        _emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})
        import traceback
        traceback.print_exc()
        return 1

    _emit({"type": "progress", "pct": 100, "detail": "KG 构建完成"})
    _emit({"type": "stage_done", "elapsed_ms": int((time.time() - t0) * 1000)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
