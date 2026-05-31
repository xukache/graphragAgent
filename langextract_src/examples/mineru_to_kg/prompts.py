"""面向知识图谱构建的 Prompt 与 Examples 定义。

设计依据：docs/mineru2langextract_handoff-v1.0.md 第 6 节。

extraction_class 体系：
- person: 人物（角色、头衔、所属机构）
- organization: 机构（类型、上级机构）
- disease: 疾病/症状
- drug: 药物（剂量、频次、适应症）
- metric: 数值指标（指标名、值、单位、方向、分组）
- cohort: 研究队列（样本量、纳入标准）
- duration: 时间周期
- publication: 发表文献
- relationship: 实体间关系
"""

from __future__ import annotations

import langextract as lx


PROMPT = (
    "从输入文本（可能包含正文、Markdown 表格、LaTeX 公式）中抽取结构化信息，用于构建知识图谱。"
    "extraction_text 尽量使用原文片段。"
    "\n\n"
    "抽取类别："
    "(1) person 人物（attributes 含 role 角色、title 头衔、affiliation 所属机构）；"
    "(2) organization 机构（attributes 含 type 类型、department 部门、parent 上级机构）；"
    "(3) disease 疾病/症状（attributes 含 category 类别）；"
    "(4) drug 药物（attributes 含 dosage 剂量、unit 单位、frequency 频次、indication 适应症、group 组别）；"
    "(5) metric 数值指标（attributes 含 metric_type 类型、metric_name 指标名、value 值、unit 单位、direction 方向、group 组别）；"
    "(6) cohort 研究队列（attributes 含 size 样本量、unit 单位、age_criteria 年龄标准、condition 纳入条件）；"
    "(7) duration 时间周期（attributes 含 value 值、unit 单位、type 类型）；"
    "(8) publication 发表文献（attributes 含 type 类型、journal_name 期刊名、year 年份、volume 卷、issue 期）；"
    "(9) relationship 实体间关系（attributes 含 head 头实体、tail 尾实体、relation_type 关系类型）。"
    "\n\n"
    "重要规则："
    "- 表格中的每一个数值都要单独抽取为 metric，attributes 中标注所在行列的语义；"
    "- 不要遗漏数值与单位；"
    "- 实体间的隶属、发表、资助、研究等关系单独抽取为 relationship；"
    "- 同一实体在不同位置出现多次，可以重复抽取，attributes 中可补充上下文。"
)


def build_examples() -> list[lx.data.ExampleData]:
    """构造抽取示例。LangExtract 强制要求至少 1 个示例。

    示例覆盖：
    - 正文实体（person / organization / disease / drug）
    - 表格数值（metric，含行列上下文）
    - 实体间关系（relationship）
    - 时间与文献（duration / publication）
    """
    return [
        lx.data.ExampleData(
            text=(
                "2022 年 5 月，北京协和医院心内科主任张伟教授发表了一项关于高血压的研究，"
                "纳入 200 名患者，使用氨氯地平治疗 6 个月。\n\n"
                "下表为各季度疗效指标：\n\n"
                "| 季度 | 收缩压(mmHg) | 舒张压(mmHg) |\n"
                "| --- | --- | --- |\n"
                "| Q1 | 145 | 92 |\n"
                "| Q4 | 130 | 82 |\n\n"
                "该研究发表于《中华心血管病杂志》2023 年第 51 卷第 3 期。"
            ),
            extractions=[
                # 人物
                lx.data.Extraction(
                    extraction_class="person",
                    extraction_text="张伟",
                    attributes={
                        "role": "心内科主任",
                        "title": "教授",
                        "affiliation": "北京协和医院",
                    },
                ),
                # 机构
                lx.data.Extraction(
                    extraction_class="organization",
                    extraction_text="北京协和医院",
                    attributes={"type": "医院", "department": "心内科"},
                ),
                # 疾病
                lx.data.Extraction(
                    extraction_class="disease",
                    extraction_text="高血压",
                    attributes={"category": "心血管疾病"},
                ),
                # 药物
                lx.data.Extraction(
                    extraction_class="drug",
                    extraction_text="氨氯地平",
                    attributes={"indication": "高血压"},
                ),
                # 队列
                lx.data.Extraction(
                    extraction_class="cohort",
                    extraction_text="200 名患者",
                    attributes={"size": "200", "unit": "patients"},
                ),
                # 时间
                lx.data.Extraction(
                    extraction_class="duration",
                    extraction_text="6 个月",
                    attributes={"value": "6", "unit": "months", "type": "治疗周期"},
                ),
                # 表格数值（每个单元格独立抽取为 metric）
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="145",
                    attributes={
                        "metric_type": "生理指标",
                        "metric_name": "收缩压",
                        "value": "145",
                        "unit": "mmHg",
                        "group": "Q1",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="130",
                    attributes={
                        "metric_type": "生理指标",
                        "metric_name": "收缩压",
                        "value": "130",
                        "unit": "mmHg",
                        "group": "Q4",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="metric",
                    extraction_text="92",
                    attributes={
                        "metric_type": "生理指标",
                        "metric_name": "舒张压",
                        "value": "92",
                        "unit": "mmHg",
                        "group": "Q1",
                    },
                ),
                # 文献
                lx.data.Extraction(
                    extraction_class="publication",
                    extraction_text="《中华心血管病杂志》2023 年第 51 卷第 3 期",
                    attributes={
                        "type": "期刊",
                        "journal_name": "中华心血管病杂志",
                        "year": "2023",
                        "volume": "51",
                        "issue": "3",
                    },
                ),
                # 关系
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="张伟 任职于 北京协和医院",
                    attributes={
                        "head": "张伟",
                        "tail": "北京协和医院",
                        "relation_type": "任职于",
                    },
                ),
                lx.data.Extraction(
                    extraction_class="relationship",
                    extraction_text="氨氯地平 治疗 高血压",
                    attributes={
                        "head": "氨氯地平",
                        "tail": "高血压",
                        "relation_type": "治疗",
                    },
                ),
            ],
        ),
    ]
