"""LangChain Tools：暴露 KG 检索能力给 Agent。

设计原则（依据 LangChain 官方 Agentic RAG 教程）：
- 每个 tool 描述清晰，让 LLM 能根据问题自主选择
- 工具返回字符串或 JSON 字符串，便于 LLM 消费
- 每次返回带 entity_id 与 source document_id，保留溯源
"""

from __future__ import annotations

import json
from typing import Optional

from langchain_core.tools import tool

from .kg_store import KGStore


# 模块级单例，由 build_tools() 注入
_STORE: KGStore | None = None


def build_tools(store: KGStore):
    """绑定 KGStore 单例，返回 LangChain tool 列表。"""
    global _STORE
    _STORE = store
    return [
        kg_summary,
        find_entities,
        list_entities_by_class,
        get_entity_detail,
        get_entity_neighbors,
        find_metrics,
    ]


def _ensure_store() -> KGStore:
    if _STORE is None:
        raise RuntimeError("KGStore 未初始化，请先调用 build_tools()")
    return _STORE


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


# --------------------------------------------------------------------------- #
# Tool 1: 整体摘要
# --------------------------------------------------------------------------- #
@tool
def kg_summary() -> str:
    """获取知识图谱整体摘要。

    返回内容包括：实体类别分布（如 metric/person/organization 等）、
    关系类型分布、每个类别下的几个示例实体。

    **使用场景**：用户问"这个文档讲什么"、"图谱里有哪些信息"、
    "有什么类型的数据"等开放性问题时优先调用。
    """
    return _dump(_ensure_store().get_summary())


# --------------------------------------------------------------------------- #
# Tool 2: 关键词检索实体
# --------------------------------------------------------------------------- #
@tool
def find_entities(query: str, limit: int = 8) -> str:
    """通过关键词在知识图谱中查找实体。

    匹配范围：实体的 label、aliases、以及 properties 字段值。
    适合用户问题中明确提到了某个名称（人名、机构名、指标名、数值等）。

    **使用场景**：
    - "张三是谁？" → query="张三"
    - "营业收入是多少" → query="营业收入"
    - "Q1 的数据" → query="Q1"

    Args:
        query: 关键词（中英文均可）
        limit: 最多返回多少个实体（默认 8）
    """
    results = _ensure_store().find_entities_by_text(query, limit=limit)
    return _dump({"query": query, "count": len(results), "entities": results})


# --------------------------------------------------------------------------- #
# Tool 3: 按类别列举
# --------------------------------------------------------------------------- #
@tool
def list_entities_by_class(entity_class: str, limit: int = 30) -> str:
    """列出某个类别的所有实体。

    可用类别：person / organization / disease / drug / metric /
    cohort / duration / publication（具体可用类别可先用 kg_summary 获取）。

    **使用场景**：
    - "文档里有哪些机构" → entity_class="organization"
    - "都有什么指标" → entity_class="metric"
    - "提到了哪些人" → entity_class="person"
    """
    results = _ensure_store().find_entities_by_class(entity_class, limit=limit)
    return _dump({"entity_class": entity_class, "count": len(results), "entities": results})


# --------------------------------------------------------------------------- #
# Tool 4: 实体详情
# --------------------------------------------------------------------------- #
@tool
def get_entity_detail(entity_id: str) -> str:
    """根据 entity_id（形如 e_xxxxxxxx）获取实体详情。

    返回完整的 properties 与 sources（出处文档与字符位置）。

    **使用场景**：从 find_entities / list_entities_by_class 拿到 entity_id 后，
    需要更详细的属性信息或溯源链路时调用。
    """
    ent = _ensure_store().get_entity(entity_id)
    if not ent:
        return _dump({"error": f"未找到 entity_id={entity_id}"})
    return _dump(ent)


# --------------------------------------------------------------------------- #
# Tool 5: 实体邻居（一跳关系）
# --------------------------------------------------------------------------- #
@tool
def get_entity_neighbors(entity_id: str, max_triples: int = 30) -> str:
    """获取某实体的所有一跳关系（出 + 入）和相邻实体。

    返回该实体涉及的全部三元组：
    - 字面量边（object 是 dict）：实体的属性值
    - 实体边（object 是另一个 entity_id）：实体之间的关系

    **使用场景**：
    - "X 和 Y 有什么关系" → 先 find_entities 找到 X，再用此工具看邻居
    - "Q1 的所有指标" → 先 find_entities 找到 _group_Q1，再用此工具
    """
    return _dump(_ensure_store().get_entity_neighbors(entity_id, max_triples=max_triples))


# --------------------------------------------------------------------------- #
# Tool 6: 数值指标专用查询
# --------------------------------------------------------------------------- #
@tool
def find_metrics(metric_name: Optional[str] = None, group: Optional[str] = None, limit: int = 30) -> str:
    """按 metric_name 和 / 或 group 过滤数值指标。

    Bridge KG 的 metric 实体含完整属性：metric_name、value、unit、group、direction。

    **使用场景**：
    - "Q1 的营业收入是多少" → metric_name="营业收入", group="Q1"
    - "毛利率分别是多少" → metric_name="毛利率"
    - "Q4 的所有数值" → group="Q4"
    - "全部指标" → 不传参数

    Args:
        metric_name: 指标名（如"营业收入"、"毛利率"），可选
        group: 分组标签（如"Q1"、"全年"），可选
        limit: 最多返回多少条（默认 30）
    """
    results = _ensure_store().find_metrics(metric_name=metric_name, group=group, limit=limit)
    return _dump({
        "metric_name": metric_name,
        "group": group,
        "count": len(results),
        "metrics": results,
    })
