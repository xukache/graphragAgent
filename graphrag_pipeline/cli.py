"""命令行测试入口：加载 KG → 构建 agent → 跑一组测试问题。

运行（在 graphrag_pipeline/.venv 内）：
    cd graphrag_pipeline
    uv run python -m graphrag_pipeline.cli                  # 跑预置测试集
    uv run python -m graphrag_pipeline.cli --question "Q1 的营业收入是多少？"
    uv run python -m graphrag_pipeline.cli --interactive    # 交互模式
"""

from __future__ import annotations

import argparse
import json
import sys
import time

from .agent import ask, build_agent
from .config import get_kg_path
from .kg_store import KGStore


# 默认测试题（覆盖不同检索路径）
DEFAULT_QUESTIONS = [
    "知识图谱里有什么类型的信息？",
    "Q1 的营业收入是多少？",
    "Q4 的毛利率是多少？",
    "全年的净利润是多少？单位是什么？",
    "图谱里提到了哪些机构？",
    "毛利率从 Q1 到 Q4 的变化趋势？",
]


def _print_result(r: dict) -> None:
    print(f"\n问：{r['question']}")
    print(f"工具调用 {r['tool_call_count']} 次：")
    for call in r["tool_calls"]:
        args_str = json.dumps(call["args"], ensure_ascii=False)
        print(f"  → {call['name']}({args_str})")
    print(f"答：{r['answer']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="GraphRAG Agentic RAG CLI")
    parser.add_argument("--question", "-q", help="单个问题")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互模式")
    parser.add_argument("--kg", help="覆盖 .env 中的 KG_JSON_PATH")
    args = parser.parse_args()

    print("=" * 70)
    print("GraphRAG Agentic RAG MVP")
    print("=" * 70)

    # 加载 KG
    kg_path = args.kg or str(get_kg_path())
    print(f"加载 KG: {kg_path}")
    t0 = time.time()
    store = KGStore.from_json(kg_path)
    print(
        f"  实体: {len(store.entities)}，三元组: {len(store.triples)}，"
        f"类别: {sorted(store.class_index.keys())}"
    )
    print(f"  加载耗时: {time.time() - t0:.2f}s")

    # 构建 agent
    print("\n构建 Agent ...")
    t1 = time.time()
    agent = build_agent(store)
    print(f"  耗时: {time.time() - t1:.2f}s")

    if args.interactive:
        print("\n进入交互模式（Ctrl-C 退出）")
        try:
            while True:
                q = input("\n问题> ").strip()
                if not q:
                    continue
                _print_result(ask(agent, q))
        except (KeyboardInterrupt, EOFError):
            print("\n退出。")
            return

    if args.question:
        _print_result(ask(agent, args.question))
        return

    # 默认跑测试集
    print(f"\n跑预置测试题（共 {len(DEFAULT_QUESTIONS)} 道）...")
    print("=" * 70)
    for q in DEFAULT_QUESTIONS:
        try:
            _print_result(ask(agent, q))
        except Exception as exc:
            print(f"\n问：{q}\n❌ 失败：{type(exc).__name__}: {exc}")
        print("-" * 70)


if __name__ == "__main__":
    main()
