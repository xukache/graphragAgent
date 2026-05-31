"""MinerU → LangExtract 端到端对接 pipeline。

设计依据：docs/mineru2langextract_handoff-v1.0.md

完整链路：
    读取 mineru_mvp/output/{uuid}_content_list.json
      -> 转换为 list[Document]（按页分组，table → Markdown）
      -> 调用 lx.extract()（Qwen via OpenAI-compatible 端点）
      -> 落盘三类产物（JSONL / 扁平 JSON / HTML 可视化）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# DashScope 是国内域名，本机 SOCKS 代理会触发 SSL EOF
for _k in (
    "ALL_PROXY", "all_proxy",
    "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy",
):
    os.environ.pop(_k, None)

from dotenv import load_dotenv

import langextract as lx
from langextract.factory import ModelConfig

# 包内导入（用 -m 运行时生效）
from .converter import content_list_to_documents, load_content_list
from .kg_builder import build_knowledge_graph
from .prompts import PROMPT, build_examples


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
DEFAULT_MINERU_OUTPUT = (BASE_DIR / "../../../mineru_mvp/output").resolve()


# --------------------------------------------------------------------------- #
# 配置加载
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    """加载 Qwen 配置。优先用本目录 .env，fallback 到 qwen_mvp/.env。"""
    candidates = [
        BASE_DIR / ".env",
        BASE_DIR.parent / "qwen_mvp" / ".env",
    ]
    loaded_from = None
    for env_path in candidates:
        if env_path.exists():
            load_dotenv(env_path)
            loaded_from = env_path
            break

    api_key = os.getenv("QWEN_API_KEY", "").strip()
    api_base = os.getenv("QWEN_API_BASE", "").strip()
    model_id = os.getenv("QWEN_LLM_MODEL", "").strip()
    if not (api_key and api_base and model_id):
        raise RuntimeError(
            "缺少 QWEN_API_KEY / QWEN_API_BASE / QWEN_LLM_MODEL，请配置 .env"
        )

    return {
        "api_key": api_key,
        "api_base": api_base,
        "model_id": model_id,
        "env_source": str(loaded_from) if loaded_from else None,
    }


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run_pipeline(mineru_output_dir: Path, output_dir: Path) -> None:
    cfg = load_config()
    output_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("MinerU → LangExtract 知识图谱抽取 Pipeline")
    print(f"MinerU 输出: {mineru_output_dir}")
    print(f"抽取结果输出: {output_dir}")
    print(f"模型: {cfg['model_id']} @ {cfg['api_base']}")
    print(f"配置来源: {cfg['env_source']}")
    print("=" * 70)

    # [1] 加载 MinerU content_list 并转换为 Document
    print("\n[1/5] 加载 MinerU content_list 并转换")
    blocks, source_file = load_content_list(mineru_output_dir)
    print(f"      加载块数: {len(blocks)}（来自 {source_file}）")

    documents = content_list_to_documents(blocks, source_file)
    print(f"      生成 Document 数: {len(documents)}")
    for doc in documents:
        print(f"        - {doc.document_id}（{len(doc.text)} 字符）")

    if not documents:
        raise RuntimeError("转换后无可用 Document")

    # [2] 构造 LangExtract 调用配置
    print("\n[2/5] 构造模型配置（Qwen via OpenAI-compatible）")
    examples = build_examples()
    print(
        f"      examples: {len(examples)} 个（共 "
        f"{sum(len(e.extractions) for e in examples)} 个示范 extraction）"
    )

    model_config = ModelConfig(
        model_id=cfg["model_id"],
        provider="OpenAILanguageModel",
        provider_kwargs={
            "api_key": cfg["api_key"],
            "base_url": cfg["api_base"],
            "format_type": lx.data.FormatType.JSON,
            "temperature": 0.0,
            "max_workers": 4,
        },
    )

    # [3] 调用 lx.extract()
    print("\n[3/5] 调用 lx.extract() 抽取结构化信息")

    max_attempts = 3
    results = None
    for attempt in range(1, max_attempts + 1):
        results = lx.extract(
            text_or_documents=documents,
            prompt_description=PROMPT,
            examples=examples,
            config=model_config,
            use_schema_constraints=False,
            fence_output=True,
        )
        # 单 Document 时返回单个对象，多 Document 返回 list
        results_list = results if isinstance(results, list) else [results]
        total = sum(len(r.extractions or []) for r in results_list)
        if total > 0:
            results = results_list
            print(f"      抽取完成（第 {attempt}/{max_attempts} 次尝试）：{total} 条 extraction")
            break
        if attempt < max_attempts:
            print(f"      第 {attempt}/{max_attempts} 次抽取返回 0 条（LLM 可能未严格遵循 JSON 格式），重试...")
        else:
            print(f"      ⚠️ 重试 {max_attempts} 次后仍为 0 条，可能需要调整 prompt 或换模型")
            results = results_list

    total_extractions = sum(len(r.extractions or []) for r in results)
    print(f"      共 {len(results)} 个 Document，{total_extractions} 条 extraction")

    # [4] 落盘
    print("\n[4/5] 落盘抽取结果")

    # 4a. 标准 JSONL
    jsonl_path = output_dir / "extraction_results.jsonl"
    lx.io.save_annotated_documents(
        results,
        output_name=jsonl_path.name,
        output_dir=str(output_dir),
    )
    print(f"      JSONL: {jsonl_path}")

    # 4b. 扁平 JSON（人类阅读）
    flat: list[dict] = []
    for r in results:
        for ex in r.extractions or []:
            flat.append({
                "document_id": r.document_id,
                "extraction_class": ex.extraction_class,
                "extraction_text": ex.extraction_text,
                "attributes": ex.attributes,
                "char_interval": (
                    {"start_pos": ex.char_interval.start_pos, "end_pos": ex.char_interval.end_pos}
                    if ex.char_interval else None
                ),
                "alignment_status": (
                    ex.alignment_status.value if ex.alignment_status else None
                ),
            })
    raw_path = output_dir / "extractions_raw.json"
    raw_path.write_text(
        json.dumps(flat, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"      扁平 JSON: {raw_path}（{len(flat)} 条）")

    # 4c. HTML 可视化
    try:
        html = lx.visualize(str(jsonl_path))
        html_str = html if isinstance(html, str) else getattr(html, "data", str(html))
        html_path = output_dir / "visualization.html"
        html_path.write_text(html_str, encoding="utf-8")
        print(f"      HTML 可视化: {html_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"      HTML 可视化失败（可忽略）: {exc}")

    # 类别统计与对齐分布
    from collections import Counter
    cls_counter: Counter = Counter()
    align_counter: Counter = Counter()
    for ex in flat:
        cls_counter[ex["extraction_class"]] += 1
        align_counter[ex["alignment_status"]] += 1

    print("\n      按 extraction_class 统计：")
    for cls, n in sorted(cls_counter.items()):
        print(f"        {cls}: {n}")
    print("\n      对齐状态分布：")
    for status, n in align_counter.items():
        print(f"        {status}: {n}")

    # [5] 构建知识图谱
    print("\n[5/5] 构建知识图谱（实体归一化 + 三元组生成）")
    kg_json, cypher, summary = build_knowledge_graph(flat)

    kg_path = output_dir / "knowledge_graph.json"
    kg_path.write_text(
        json.dumps(kg_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"      KG JSON: {kg_path}")
    print(f"        实体节点：{kg_json['stats']['entity_count']}")
    print(f"        三元组：{kg_json['stats']['triple_count']}")
    print(f"        按类别：{kg_json['stats']['by_class']}")
    print(f"        按谓词：{kg_json['stats']['by_predicate']}")

    cypher_path = output_dir / "knowledge_graph.cypher"
    cypher_path.write_text(cypher, encoding="utf-8")
    print(f"      Cypher（Neo4j 导入脚本）: {cypher_path}")

    summary_path = output_dir / "knowledge_graph.md"
    summary_path.write_text(summary, encoding="utf-8")
    print(f"      Markdown 摘要: {summary_path}")

    print("\n" + "=" * 70)
    print("Pipeline 执行完成 ✅")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="MinerU → LangExtract 对接 pipeline")
    parser.add_argument(
        "--mineru-output",
        type=Path,
        default=DEFAULT_MINERU_OUTPUT,
        help=f"MinerU 输出目录（默认 {DEFAULT_MINERU_OUTPUT}）",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help=f"抽取结果输出目录（默认 {OUTPUT_DIR}）",
    )
    args = parser.parse_args()

    try:
        run_pipeline(args.mineru_output.resolve(), args.output_dir.resolve())
    except Exception as exc:
        print(f"\n❌ Pipeline 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
