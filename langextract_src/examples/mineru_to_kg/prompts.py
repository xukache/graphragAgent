"""面向知识图谱构建的 Prompt 与 Examples 定义。

设计依据：
- docs/mineru2langextract_handoff-v1.0.md（转换层）
- docs/superpowers/plans/2026-06-01-langextract-quality-impl.md（质量改进）

v2 关键变化（2026-06-01）：
- 开放 entity schema：LLM 根据文档内容决定 3-8 个适合的 class（不再硬编码 9 类）
- 受控 relation 词表：10 个通用动词，强制从词表中选
- extraction_text 必须是原文 substring（避免 FAILED to align 警告与编造）
- 3 个跨领域 examples（财务/学术/医学），全部 substring 合规
"""

from __future__ import annotations

import langextract as lx


PROMPT = (
    "阅读整段文本，根据内容决定 3-8 个适合本篇文档的 entity class "
    "（中英文名皆可，列在每个 JSON 抽取组的 'class' 字段）。\n\n"
    "对每个抽取项：\n"
    "  - extraction_text 必须是原文 substring（逐字一致，不能改写、不能拼接、不能翻译）\n"
    "  - 若文本中出现引用编号（如 [87, 120]），请归类为 'reference'\n\n"
    "关系抽取必须从以下 10 个谓词中选取，不要自创新词：\n"
    "  mentions / discusses / proposes / extends / evaluates / uses /\n"
    "  affiliated_with / published_in / part_of / cites\n\n"
    "对每个 relationship，extraction_text 应该是该关系在原文中最短的对应片段"
    "（如 \"任职于\" 即可），attributes 里给出 head / tail / relation_type。"
)


def build_examples() -> list[lx.data.ExampleData]:
    """构造 3 个跨领域抽取示例。LangExtract 强制要求至少 1 个示例。

    所有 extraction_text 严格 = text 的 substring（substring 合规才能让
    LangExtract 的 auto-alignment 报 match_exact，从而消除 FAILED to align 警告）。

    示例覆盖：
    - 财务（净利润/季度/数值）
    - 学术（作者/机构/论文 + 引用编号归 reference）
    - 医学（药物/疾病/研究）
    """
    return [
        # ---------- 示例 1：财务（财报 / 季度数值） ----------
        lx.data.ExampleData(
            text=(
                "2023 年 Q1，腾讯营业收入 1499.86 亿元人民币，同比增长 11%。"
                "净利润 258.38 亿元，毛利率 45.5%。"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="company",
                    extraction_text="腾讯",
                    attributes={"type": "互联网公司"},
                ),
                lx.data.Extraction(
                    extraction_class="period",
                    extraction_text="Q1",
                    attributes={"year": "2023"},
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="1499.86",
                    attributes={
                        "metric_name": "营业收入",
                        "value": "1499.86",
                        "unit": "亿元人民币",
                        "group": "2023 Q1",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="258.38",
                    attributes={
                        "metric_name": "净利润",
                        "value": "258.38",
                        "unit": "亿元人民币",
                        "group": "2023 Q1",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="45.5",
                    attributes={
                        "metric_name": "毛利率",
                        "value": "45.5",
                        "unit": "%",
                        "group": "2023 Q1",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="营业收入",
                    attributes={
                        "head": "腾讯",
                        "tail": "营业收入",
                        "relation_type": "mentions",
                    },
                ),
            ],
        ),
        # ---------- 示例 2：学术（作者/机构/论文 + 引用编号归 reference） ----------
        lx.data.ExampleData(
            text=(
                "Haoyu Han 现任职于 Michigan State University，"
                "Yu Wang 任职于 University of Oregon。"
                "他们的论文 [120] 调研了 GraphRAG 的方法。"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="author",
                    extraction_text="Haoyu Han",
                    attributes={"affiliation": "Michigan State University"},
                ),
                lx.data.Extraction(
                    extraction_class="author",
                    extraction_text="Yu Wang",
                    attributes={"affiliation": "University of Oregon"},
                ),
                lx.data.Extraction(
                    extraction_class="institution",
                    extraction_text="Michigan State University",
                    attributes={"type": "大学"},
                ),
                lx.data.Extraction(
                    extraction_class="institution",
                    extraction_text="University of Oregon",
                    attributes={"type": "大学"},
                ),
                lx.data.Extraction(
                    extraction_class="reference",
                    extraction_text="[120]",
                    attributes={"type": "citation"},
                ),
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="任职于",
                    attributes={
                        "head": "Haoyu Han",
                        "tail": "Michigan State University",
                        "relation_type": "affiliated_with",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="调研了",
                    attributes={
                        "head": "[120]",
                        "tail": "GraphRAG",
                        "relation_type": "discusses",
                    },
                ),
            ],
        ),
        # ---------- 示例 3：医学（药物/疾病/治疗） ----------
        lx.data.ExampleData(
            text=(
                "2022 年 5 月，张伟在北京协和医院使用氨氯地平治疗高血压患者。"
                "研究纳入 200 名患者，随访 6 个月。"
            ),
            extractions=[
                lx.data.Extraction(
                    extraction_class="researcher",
                    extraction_text="张伟",
                    attributes={"affiliation": "北京协和医院"},
                ),
                lx.data.Extraction(
                    extraction_class="institution",
                    extraction_text="北京协和医院",
                    attributes={"type": "医院"},
                ),
                lx.data.Extraction(
                    extraction_class="drug",
                    extraction_text="氨氯地平",
                    attributes={"indication": "高血压"},
                ),
                lx.data.Extraction(
                    extraction_class="disease",
                    extraction_text="高血压",
                    attributes={"category": "心血管疾病"},
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
                    extraction_class="relationship",
                    extraction_text="使用",
                    attributes={
                        "head": "张伟",
                        "tail": "氨氯地平",
                        "relation_type": "uses",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="治疗",
                    attributes={
                        "head": "氨氯地平",
                        "tail": "高血压",
                        "relation_type": "evaluates",
                    },
                ),
            ],
        ),
    ]
