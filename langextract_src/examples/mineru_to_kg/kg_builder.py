"""知识图谱构建器：实体归一化 + 三元组生成 + 多格式导出。

设计依据：docs/mineru2langextract_handoff-v1.0.md 第 8 节后处理规划。

核心流程：
    extractions（来自 LangExtract）
      -> normalize_entities()    分配 canonical entity_id，相同实体合并
      -> generate_triples()       生成 (head, relation, tail) 三元组
                                   - 显式：relationship 类抽取
                                   - 隐式：从 attributes 推导（如 person.affiliation）
                                   - 数值：metric 的 group → metric 的 value
      -> export_*()               JSON 三元组 / Neo4j Cypher / Markdown 摘要

不引入新依赖（不依赖 networkx）。下游想用图算法时可自行 load JSON 到 networkx/Neo4j。
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any


# --------------------------------------------------------------------------- #
# 数据结构
# --------------------------------------------------------------------------- #
@dataclass
class Entity:
    """归一化后的实体节点。"""
    entity_id: str
    entity_class: str  # = extraction_class
    label: str         # 规范化的显示名
    aliases: set[str] = field(default_factory=set)
    properties: dict[str, Any] = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)  # 出处（document_id / char_interval）

    def to_dict(self) -> dict:
        return {
            "entity_id": self.entity_id,
            "entity_class": self.entity_class,
            "label": self.label,
            "aliases": sorted(self.aliases),
            "properties": self.properties,
            "sources": self.sources,
        }


@dataclass
class Triple:
    """知识图谱三元组。"""
    subject: str    # entity_id
    predicate: str  # 关系名
    obj: str | dict  # entity_id（图节点）或 literal dict {"value": ..., "unit": ...}
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "subject": self.subject,
            "predicate": self.predicate,
            "object": self.obj,
            "metadata": self.metadata,
        }


# --------------------------------------------------------------------------- #
# 实体归一化
# --------------------------------------------------------------------------- #
_NORMALIZE_RE = re.compile(r"\s+")


def _norm_text(text: str) -> str:
    """文本归一化：去除首尾空白、压缩内部空白、保留原始大小写与中文。"""
    return _NORMALIZE_RE.sub(" ", (text or "").strip())


def _entity_signature(entity_class: str, label: str, attrs: dict) -> str:
    """生成实体签名（用于去重）。

    metric 类用 metric_name + value + group + unit 组合（每个数值是独立实体）。
    其他类用 class + 归一化 label + 关键 attrs。
    """
    if entity_class == "metric":
        keys = ("metric_name", "value", "group", "unit")
        attr_part = "|".join(str(attrs.get(k, "")) for k in keys)
        return f"metric|{attr_part}"
    if entity_class == "person":
        # 同名同 affiliation 视为同一人
        affiliation = attrs.get("affiliation", "")
        return f"person|{label}|{affiliation}"
    return f"{entity_class}|{label}"


def _make_entity_id(signature: str) -> str:
    """从签名生成短 entity_id。"""
    h = hashlib.sha1(signature.encode("utf-8")).hexdigest()[:8]
    return f"e_{h}"


def normalize_entities(extractions: list[dict]) -> dict[str, Entity]:
    """合并重复实体，返回 {entity_id: Entity}。

    输入 extractions 应是扁平字典列表（来自 extractions_raw.json 格式）。
    """
    entities: dict[str, Entity] = {}
    # 跳过 relationship —— 它在 generate_triples 中处理，本身不是节点
    for ex in extractions:
        cls = ex.get("extraction_class", "")
        if cls == "relationship":
            continue

        text = _norm_text(ex.get("extraction_text", ""))
        if not text:
            continue
        attrs = ex.get("attributes") or {}

        sig = _entity_signature(cls, text, attrs)
        eid = _make_entity_id(sig)

        if eid not in entities:
            label = text
            # metric 实体的 label 用 "metric_name (group)" 更可读
            if cls == "metric":
                metric_name = attrs.get("metric_name") or "未命名指标"
                group = attrs.get("group")
                label = f"{metric_name}（{group}）" if group else metric_name
            entities[eid] = Entity(
                entity_id=eid,
                entity_class=cls,
                label=label,
                aliases={text} if text != label else set(),
                properties=dict(attrs),
                sources=[],
            )
        else:
            # 合并：aliases + 属性（取并集，冲突时保留首次值）
            entities[eid].aliases.add(text)
            for k, v in attrs.items():
                if k not in entities[eid].properties:
                    entities[eid].properties[k] = v

        entities[eid].sources.append(
            {
                "document_id": ex.get("document_id"),
                "char_interval": ex.get("char_interval"),
                "alignment_status": ex.get("alignment_status"),
            }
        )

    return entities


def _find_entity_by_label(entities: dict[str, Entity], label: str) -> str | None:
    """按 label 或 alias 查找 entity_id。返回 None 表示找不到。"""
    target = _norm_text(label)
    if not target:
        return None
    for eid, ent in entities.items():
        if _norm_text(ent.label) == target or target in {_norm_text(a) for a in ent.aliases}:
            return eid
    # 子串匹配（处理"华山医院" 与 "复旦大学附属华山医院"）
    for eid, ent in entities.items():
        if target in ent.label or ent.label in target:
            return eid
    return None


# --------------------------------------------------------------------------- #
# 三元组生成
# --------------------------------------------------------------------------- #

# 隐式关系规则：(extraction_class, attribute_key) -> predicate
# - 若 attribute 值能匹配到已有实体，生成 entity-entity 三元组
# - 否则生成 entity-literal 三元组（object 为 dict）
ATTR_TO_PREDICATE: dict[tuple[str, str], str] = {
    ("person", "affiliation"): "affiliated_with",
    ("person", "role"): "has_role",
    ("person", "title"): "has_title",
    ("organization", "parent"): "sub_org_of",
    ("organization", "department"): "has_department",
    ("organization", "type"): "org_type",
    ("drug", "indication"): "indicates",
    ("drug", "group"): "in_group",
    ("disease", "category"): "disease_category",
    ("publication", "journal_name"): "published_in",
    ("publication", "year"): "published_year",
    ("publication", "volume"): "volume",
    ("publication", "issue"): "issue",
    ("cohort", "condition"): "cohort_condition",
    ("cohort", "size"): "cohort_size",
    ("duration", "value"): "duration_value",
    ("duration", "unit"): "duration_unit",
    ("duration", "type"): "duration_type",
}


def generate_triples(
    extractions: list[dict], entities: dict[str, Entity]
) -> list[Triple]:
    """从抽取结果与归一化实体生成三元组。

    三类来源：
    1. relationship 类抽取 → 直接三元组
    2. metric 类 → (group, has_<metric_name>, value+unit)
    3. 其他类的 attributes → 隐式三元组（entity-entity 或 entity-literal）
    """
    triples: list[Triple] = []

    for ex in extractions:
        cls = ex.get("extraction_class", "")
        attrs = ex.get("attributes") or {}
        text = _norm_text(ex.get("extraction_text", ""))
        meta = {
            "document_id": ex.get("document_id"),
            "extraction_class": cls,
        }

        # ----- 1. relationship 类直接三元组 -----
        if cls == "relationship":
            head = attrs.get("head") or ""
            tail = attrs.get("tail") or ""
            pred = attrs.get("relation_type") or "related_to"
            head_id = _find_entity_by_label(entities, head)
            tail_id = _find_entity_by_label(entities, tail)
            if head_id and tail_id:
                triples.append(Triple(head_id, pred, tail_id, meta))
            else:
                # 尾节点是 literal 时仍记录
                triples.append(
                    Triple(
                        head_id or f"_unresolved_{_norm_text(head)}",
                        pred,
                        tail_id or {"value": tail},
                        {**meta, "warning": "head_or_tail_unresolved"},
                    )
                )
            continue

        # 找到当前抽取对应的 entity_id
        sig = _entity_signature(cls, text, attrs)
        eid = _make_entity_id(sig)
        if eid not in entities:
            continue

        # ----- 2. metric 类 -----
        if cls == "metric":
            group = attrs.get("group")
            metric_name = attrs.get("metric_name") or "value"
            value = attrs.get("value") or text
            unit = attrs.get("unit")
            if group:
                # (group_label, has_<metric_name>, value+unit)
                triples.append(
                    Triple(
                        subject=f"_group_{_norm_text(group)}",
                        predicate=f"has_{metric_name}",
                        obj={"value": value, "unit": unit, "metric_id": eid},
                        metadata={**meta, "group_label": group},
                    )
                )
            # 同时记录 entity-self literal（便于查询所有 metric 节点）
            triples.append(
                Triple(
                    subject=eid,
                    predicate="has_value",
                    obj={"value": value, "unit": unit},
                    metadata=meta,
                )
            )
            continue

        # ----- 3. 其他类：从 attributes 推导隐式三元组 -----
        for attr_key, attr_val in attrs.items():
            pred = ATTR_TO_PREDICATE.get((cls, attr_key))
            if not pred or attr_val in (None, ""):
                continue
            # 优先尝试解析为已存在的实体
            tail_id = _find_entity_by_label(entities, str(attr_val))
            if tail_id and tail_id != eid:
                triples.append(Triple(eid, pred, tail_id, meta))
            else:
                triples.append(
                    Triple(
                        eid,
                        pred,
                        {"value": attr_val},
                        meta,
                    )
                )

    return triples


# --------------------------------------------------------------------------- #
# 导出
# --------------------------------------------------------------------------- #
def export_json(
    entities: dict[str, Entity], triples: list[Triple]
) -> dict:
    """生成 JSON 知识图谱（节点 + 边）。"""
    return {
        "entities": [e.to_dict() for e in entities.values()],
        "triples": [t.to_dict() for t in triples],
        "stats": {
            "entity_count": len(entities),
            "triple_count": len(triples),
            "by_class": dict(Counter(e.entity_class for e in entities.values())),
            "by_predicate": dict(Counter(t.predicate for t in triples)),
        },
    }


def _cypher_escape(s: str) -> str:
    """转义 Cypher 字符串字面量。"""
    return (s or "").replace("\\", "\\\\").replace("'", "\\'")


def export_cypher(entities: dict[str, Entity], triples: list[Triple]) -> str:
    """生成 Neo4j Cypher 导入脚本。"""
    lines = ["// MinerU → LangExtract 知识图谱 Cypher 导入脚本", ""]
    lines.append("// === 节点 ===")
    for ent in entities.values():
        label = ent.entity_class.capitalize()
        props_pairs = [f"id: '{ent.entity_id}'", f"label: '{_cypher_escape(ent.label)}'"]
        for k, v in ent.properties.items():
            if v is None:
                continue
            props_pairs.append(f"{k}: '{_cypher_escape(str(v))}'")
        if ent.aliases:
            aliases_str = ", ".join(f"'{_cypher_escape(a)}'" for a in sorted(ent.aliases))
            props_pairs.append(f"aliases: [{aliases_str}]")
        props = ", ".join(props_pairs)
        lines.append(f"MERGE (n:{label} {{ id: '{ent.entity_id}' }}) SET n += {{{props}}};")

    lines.append("")
    lines.append("// === 关系 ===")
    for tri in triples:
        # entity → entity 边
        if isinstance(tri.obj, str) and tri.obj in entities:
            pred = re.sub(r"\W+", "_", tri.predicate).upper()
            lines.append(
                f"MATCH (a {{id: '{tri.subject}'}}), (b {{id: '{tri.obj}'}}) "
                f"MERGE (a)-[:{pred}]->(b);"
            )
        # 其他（literal 或未解析）作为节点属性写入注释
    return "\n".join(lines) + "\n"


def export_markdown_summary(
    entities: dict[str, Entity], triples: list[Triple]
) -> str:
    """生成人类阅读友好的摘要报告。"""
    by_class: dict[str, list[Entity]] = defaultdict(list)
    for e in entities.values():
        by_class[e.entity_class].append(e)

    by_pred: dict[str, list[Triple]] = defaultdict(list)
    for t in triples:
        by_pred[t.predicate].append(t)

    lines = ["# 知识图谱摘要", "", "## 概览", ""]
    lines.append(f"- 实体节点数：**{len(entities)}**")
    lines.append(f"- 三元组数：**{len(triples)}**")
    lines.append(f"- 实体类别：{', '.join(f'`{c}`×{len(es)}' for c, es in sorted(by_class.items()))}")
    lines.append("")

    lines.append("## 实体节点")
    lines.append("")
    for cls in sorted(by_class.keys()):
        lines.append(f"### {cls}（{len(by_class[cls])} 个）")
        lines.append("")
        for e in by_class[cls]:
            extra = ""
            key_attrs = {
                k: v for k, v in e.properties.items() if v not in (None, "")
            }
            if key_attrs:
                kv = ", ".join(f"{k}={v}" for k, v in list(key_attrs.items())[:5])
                extra = f"  — {kv}"
            lines.append(f"- `{e.entity_id}` **{e.label}**{extra}")
        lines.append("")

    lines.append("## 三元组（按谓词分组）")
    lines.append("")
    for pred in sorted(by_pred.keys()):
        lines.append(f"### `{pred}`（{len(by_pred[pred])} 条）")
        lines.append("")
        for t in by_pred[pred][:20]:  # 每谓词最多展示 20 条
            obj_str = (
                t.obj
                if isinstance(t.obj, str)
                else f"`{json.dumps(t.obj, ensure_ascii=False)}`"
            )
            lines.append(f"- `{t.subject}` → `{obj_str}`")
        if len(by_pred[pred]) > 20:
            lines.append(f"- ... 共 {len(by_pred[pred])} 条")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 一站式入口
# --------------------------------------------------------------------------- #
def build_knowledge_graph(extractions: list[dict]) -> tuple[dict, str, str]:
    """从扁平 extractions 列表构建知识图谱。

    Returns:
        (json_dict, cypher_text, markdown_summary)
    """
    entities = normalize_entities(extractions)
    triples = generate_triples(extractions, entities)
    return (
        export_json(entities, triples),
        export_cypher(entities, triples),
        export_markdown_summary(entities, triples),
    )


if __name__ == "__main__":
    # 自测：从 output/extractions_raw.json 读取并生成 KG
    import sys
    from pathlib import Path

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("examples/mineru_to_kg/output/extractions_raw.json")
    extractions = json.loads(target.read_text(encoding="utf-8"))
    kg, cypher, summary = build_knowledge_graph(extractions)
    print(f"实体数: {kg['stats']['entity_count']}")
    print(f"三元组数: {kg['stats']['triple_count']}")
    print(f"按类别: {kg['stats']['by_class']}")
    print(f"按谓词: {kg['stats']['by_predicate']}")
    print()
    print("--- Markdown 摘要预览 ---")
    print(summary[:1500])
