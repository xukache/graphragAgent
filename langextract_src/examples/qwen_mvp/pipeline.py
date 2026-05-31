"""LangExtract MVP pipeline，使用阿里千问（OpenAI-compatible 端点）。

依据 docs/langextract_pipeline_spec.md 实现完整链路：
    1. 文本输入（模拟数据）
    2. 通过 ModelConfig 接入 Qwen OpenAI-compatible 端点
    3. langextract.extract() 结构化抽取
    4. 结果落盘（JSONL + HTML 可视化）
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# DashScope 是国内域名，通过本机代理会触发 SSL EOF；提前清理代理变量
for _k in (
    "ALL_PROXY", "all_proxy",
    "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy",
):
    os.environ.pop(_k, None)

from dotenv import load_dotenv

import langextract as lx
from langextract.factory import ModelConfig


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


# --------------------------------------------------------------------------- #
# 配置
# --------------------------------------------------------------------------- #
def load_config() -> dict:
    load_dotenv(BASE_DIR / ".env")
    api_key = os.getenv("QWEN_API_KEY", "").strip()
    api_base = os.getenv("QWEN_API_BASE", "").strip()
    model_id = os.getenv("QWEN_LLM_MODEL", "").strip()
    if not (api_key and api_base and model_id):
        raise RuntimeError("缺少 QWEN_API_KEY / QWEN_API_BASE / QWEN_LLM_MODEL")
    return {"api_key": api_key, "api_base": api_base, "model_id": model_id}


# --------------------------------------------------------------------------- #
# 模拟输入数据（中文医学/科研文本，含人物、机构、疾病、药物、时间等实体）
# --------------------------------------------------------------------------- #
SAMPLE_TEXT = (
    "2023 年 3 月，复旦大学附属华山医院神经内科主任王明远教授主持完成了一项关于阿尔茨海默病的"
    "临床研究。研究纳入 312 名 65 岁以上的轻度认知障碍患者，随机分为两组：实验组每日服用多奈"
    "哌齐 10 毫克，对照组服用安慰剂。经过 12 个月的随访，实验组的 MMSE 评分平均提升 2.4 分，"
    "对照组下降 0.8 分（p<0.01）。该研究由国家自然科学基金资助，论文已发表于《柳叶刀-神经学》"
    "2024 年第 23 卷第 5 期。共同第一作者李芳博士同时任职于上海交通大学医学院。"
)


def build_examples() -> list[lx.data.ExampleData]:
    """构造抽取示例。LangExtract 强制要求至少 1 个示例。"""
    return [
        lx.data.ExampleData(
            text=(
                "2022 年 5 月，北京协和医院心内科主任张伟教授发表了一项关于高血压的研究，"
                "纳入 200 名患者，使用氨氯地平治疗 6 个月，收缩压平均下降 15 mmHg。"
                "该研究发表于《中华心血管病杂志》。"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="person",
                    extraction_text="张伟",
                    attributes={"role": "心内科主任", "title": "教授"},
                ),
                lx.data.Extraction(
                    extraction_class="organization",
                    extraction_text="北京协和医院",
                    attributes={"type": "医院", "department": "心内科"},
                ),
                lx.data.Extraction(
                    extraction_class="disease",
                    extraction_text="高血压",
                    attributes={"category": "心血管疾病"},
                ),
                lx.data.Extraction(
                    extraction_class="drug",
                    extraction_text="氨氯地平",
                    attributes={"indication": "高血压"},
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="收缩压平均下降 15 mmHg",
                    attributes={"metric_type": "疗效", "value": "15", "unit": "mmHg"},
                ),
                lx.data.Extraction(
                    extraction_class="cohort",
                    extraction_text="200 名患者",
                    attributes={"size": "200", "unit": "patients"},
                ),
                lx.data.Extraction(
                    extraction_class="duration",
                    extraction_text="6 个月",
                    attributes={"value": "6", "unit": "months"},
                ),
                lx.data.Extraction(
                    extraction_class="publication",
                    extraction_text="《中华心血管病杂志》",
                    attributes={"type": "期刊"},
                ),
            ],
        ),
    ]


PROMPT = (
    "从中文临床/科研文本中抽取以下结构化信息，每个抽取项尽量使用原文片段作为 extraction_text："
    " (1) person 研究者/作者姓名；(2) organization 机构/医院/院系；"
    "(3) disease 疾病；(4) drug 药物；(5) metric 关键数值或疗效指标；"
    "(6) cohort 队列规模；(7) duration 研究周期；(8) publication 发表期刊或文章。"
    " 不要遗漏数值与单位；attributes 中尽量补充类型、单位、值、角色等可解析字段。"
)


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def run_pipeline() -> None:
    cfg = load_config()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 70)
    print("LangExtract MVP Pipeline (Qwen via OpenAI-compatible)")
    print(f"Model:    {cfg['model_id']}")
    print(f"Base URL: {cfg['api_base']}")
    print("=" * 70)

    # 1) 输入文本
    print("\n[1/4] 准备输入文本")
    print(f"      字符数: {len(SAMPLE_TEXT)}")
    print(f"      预览:   {SAMPLE_TEXT[:60]}...")

    examples = build_examples()
    print(f"      示例数: {len(examples)}（含 {sum(len(e.extractions) for e in examples)} 个 extraction）")

    # 2) 构造模型配置（OpenAI-compatible 端点接入 Qwen）
    print("\n[2/4] 构造模型配置（OpenAI-compatible 接入 Qwen）")
    model_config = ModelConfig(
        model_id=cfg["model_id"],
        provider="OpenAILanguageModel",  # 强制使用 OpenAI provider，绕过 model_id 自动路由
        provider_kwargs={
            "api_key": cfg["api_key"],
            "base_url": cfg["api_base"],
            "format_type": lx.data.FormatType.JSON,
            "temperature": 0.0,
            "max_workers": 4,
        },
    )

    # 3) 调用 langextract.extract()
    print("\n[3/4] 调用 langextract.extract() 进行结构化抽取")
    result = lx.extract(
        text_or_documents=SAMPLE_TEXT,
        prompt_description=PROMPT,
        examples=examples,
        config=model_config,
        # OpenAI-compatible 端点的 schema 兼容性参差，关闭 schema 约束更稳
        use_schema_constraints=False,
        fence_output=True,            # 让模型用 ```json``` 包裹输出，解析更稳
    )

    # 4) 概览 + 落盘
    print("\n[4/4] 解析结果")
    extractions = result.extractions or []
    print(f"      抽取条数: {len(extractions)}")

    # 按类别统计
    by_class: dict[str, int] = {}
    aligned = 0
    for ex in extractions:
        by_class[ex.extraction_class] = by_class.get(ex.extraction_class, 0) + 1
        if ex.char_interval is not None and ex.alignment_status is not None:
            aligned += 1
    print(f"      已对齐到原文: {aligned}/{len(extractions)}")
    print("      按类别统计:")
    for cls, n in sorted(by_class.items()):
        print(f"        {cls}: {n}")

    print("\n      抽取明细:")
    for ex in extractions:
        loc = ""
        if ex.char_interval and ex.char_interval.start_pos is not None:
            loc = f" @[{ex.char_interval.start_pos}:{ex.char_interval.end_pos}]"
        attrs = f"  attrs={ex.attributes}" if ex.attributes else ""
        print(f"        - [{ex.extraction_class}] '{ex.extraction_text}'{loc}{attrs}")

    # 保存 JSONL
    jsonl_path = OUTPUT_DIR / "extraction_results.jsonl"
    lx.io.save_annotated_documents(
        [result],
        output_name=jsonl_path.name,
        output_dir=str(OUTPUT_DIR),
    )
    print(f"\n      JSONL 已保存: {jsonl_path}")

    # 保存原始抽取（便于查看完整 attributes）
    raw_path = OUTPUT_DIR / "extractions_raw.json"
    raw_path.write_text(
        json.dumps(
            [
                {
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
                }
                for ex in extractions
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"      原始抽取已保存: {raw_path}")

    # 保存 HTML 可视化
    try:
        html = lx.visualize(str(jsonl_path))
        html_str = html if isinstance(html, str) else getattr(html, "data", str(html))
        html_path = OUTPUT_DIR / "visualization.html"
        html_path.write_text(html_str, encoding="utf-8")
        print(f"      HTML 可视化已保存: {html_path}")
    except Exception as exc:  # noqa: BLE001
        print(f"      HTML 可视化生成失败（可忽略）: {exc}")

    print("\n" + "=" * 70)
    print("Pipeline 执行完成 ✅")
    print("=" * 70)


if __name__ == "__main__":
    try:
        run_pipeline()
    except Exception as exc:
        print(f"\n❌ Pipeline 失败: {type(exc).__name__}: {exc}")
        sys.exit(1)
