"""KG 内存存储 + 检索原语（无 embedding，纯关键词/属性匹配）。

依据 docs/index_pipeline_specification-v1.0.md 第 5 节 knowledge_graph.json 实测结构：
- entities[i]: {entity_id, entity_class, label, aliases, properties, sources}
- triples[i]: {subject, predicate, object (str|dict), metadata}
- 字面量边的 object 是 dict（{value, unit, ...}），实体边的 object 是 entity_id 字符串
- subject 可能是 entity_id 或 _group_xxx 虚拟节点

本模块提供 5 类检索原语，给 Agent 工具层调用。
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class KGStore:
    """加载到内存的知识图谱。"""

    entities: dict[str, dict] = field(default_factory=dict)        # entity_id -> entity dict
    triples: list[dict] = field(default_factory=list)              # 原始三元组列表
    out_edges: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))  # subject -> triples
    in_edges: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))   # object(if str) -> triples
    label_index: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list)) # 归一化 label/alias -> entity_ids
    class_index: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list)) # entity_class -> entity_ids
    stats: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path | str) -> "KGStore":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        store = cls(
            entities={e["entity_id"]: e for e in data.get("entities", [])},
            triples=data.get("triples", []),
            stats=data.get("stats", {}),
        )
        store._build_indexes()
        return store

    def _build_indexes(self) -> None:
        for eid, ent in self.entities.items():
            self.class_index[ent.get("entity_class", "")].append(eid)
            for name in [ent.get("label", "")] + list(ent.get("aliases") or []):
                norm = _norm(name)
                if norm:
                    self.label_index[norm].append(eid)
        for tri in self.triples:
            self.out_edges[tri["subject"]].append(tri)
            obj = tri.get("object")
            if isinstance(obj, str):
                self.in_edges[obj].append(tri)

    # ------------------------------------------------------------------ #
    # 检索原语（供 tools.py 包装为 LangChain Tool）
    # ------------------------------------------------------------------ #
    def find_entities_by_text(self, query: str, limit: int = 10) -> list[dict]:
        """关键词匹配 label / aliases / properties value。

        策略：
        1. 精确归一化匹配（最高优先）
        2. 子串匹配（label / aliases）
        3. 属性值子串匹配（覆盖 metric value、metric_name 等）
        """
        q = _norm(query)
        if not q:
            return []

        scores: dict[str, float] = {}
        # 1. 归一化精确匹配
        for eid in self.label_index.get(q, []):
            scores[eid] = max(scores.get(eid, 0), 10.0)

        # 2. 子串匹配
        for norm_label, eids in self.label_index.items():
            if q in norm_label:
                w = 5.0 + len(q) / max(len(norm_label), 1)
                for eid in eids:
                    scores[eid] = max(scores.get(eid, 0), w)
            elif norm_label in q:
                for eid in eids:
                    scores[eid] = max(scores.get(eid, 0), 3.0)

        # 3. properties 值匹配
        for eid, ent in self.entities.items():
            for v in (ent.get("properties") or {}).values():
                if v is None:
                    continue
                vn = _norm(str(v))
                if vn and (q in vn or vn in q):
                    scores[eid] = max(scores.get(eid, 0), 2.0)

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[:limit]
        return [self._entity_view(self.entities[eid]) for eid, _ in ranked if eid in self.entities]

    def find_entities_by_class(self, entity_class: str, limit: int = 50) -> list[dict]:
        eids = self.class_index.get(entity_class, [])[:limit]
        return [self._entity_view(self.entities[eid]) for eid in eids]

    def get_entity(self, entity_id: str) -> dict | None:
        ent = self.entities.get(entity_id)
        return self._entity_view(ent) if ent else None

    def get_entity_neighbors(self, entity_id: str, max_triples: int = 30) -> dict:
        """返回某实体的全部三元组（出 + 入），及涉及的相邻实体。"""
        out = self.out_edges.get(entity_id, [])
        inc = self.in_edges.get(entity_id, [])
        all_triples = (out + inc)[:max_triples]

        neighbor_ids: set[str] = set()
        for tri in all_triples:
            for side in (tri.get("subject"), tri.get("object")):
                if isinstance(side, str) and side != entity_id and side in self.entities:
                    neighbor_ids.add(side)

        return {
            "entity": self._entity_view(self.entities.get(entity_id)),
            "triples": [self._triple_view(t) for t in all_triples],
            "neighbors": [self._entity_view(self.entities[nid]) for nid in neighbor_ids],
            "out_count": len(out),
            "in_count": len(inc),
        }

    def find_metrics(
        self,
        metric_name: str | None = None,
        group: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """按 metric_name / group 过滤 metric 类实体。

        Bridge KG 的设计：
        - 每个 metric 是一个独立 entity（class=metric）
        - properties 含 metric_name / value / unit / group 等
        - 同时通过虚拟节点 _group_<label> 关联到 group 维度
        """
        results: list[dict] = []
        nm = _norm(metric_name) if metric_name else None
        gm = _norm(group) if group else None

        for eid in self.class_index.get("metric", []):
            ent = self.entities.get(eid)
            if not ent:
                continue
            props = ent.get("properties") or {}
            if nm:
                pname = _norm(str(props.get("metric_name", "")))
                if nm not in pname and pname not in nm:
                    continue
            if gm:
                pgroup = _norm(str(props.get("group", "")))
                if gm not in pgroup and pgroup not in gm:
                    continue
            results.append(self._entity_view(ent))
            if len(results) >= limit:
                break
        return results

    def get_summary(self) -> dict:
        """整体摘要：实体类别分布 + 关系类型分布 + 关键示例。"""
        return {
            "stats": self.stats,
            "available_classes": sorted(self.class_index.keys()),
            "sample_entities_per_class": {
                cls: [
                    {"entity_id": eid, "label": self.entities[eid].get("label")}
                    for eid in eids[:3]
                ]
                for cls, eids in self.class_index.items()
            },
        }

    # ------------------------------------------------------------------ #
    # 视图：精简返回字段，避免给 LLM 灌噪声
    # ------------------------------------------------------------------ #
    @staticmethod
    def _entity_view(ent: dict | None) -> dict | None:
        if not ent:
            return None
        return {
            "entity_id": ent.get("entity_id"),
            "entity_class": ent.get("entity_class"),
            "label": ent.get("label"),
            "aliases": ent.get("aliases", []),
            "properties": ent.get("properties", {}),
            "sources": [
                {
                    "document_id": s.get("document_id"),
                    "char_interval": s.get("char_interval"),
                }
                for s in (ent.get("sources") or [])
            ][:3],
        }

    @staticmethod
    def _triple_view(tri: dict) -> dict:
        return {
            "subject": tri.get("subject"),
            "predicate": tri.get("predicate"),
            "object": tri.get("object"),
            "document_id": (tri.get("metadata") or {}).get("document_id"),
        }


_NORMALIZE_RE = re.compile(r"\s+")


def _norm(s: str | None) -> str:
    if not s:
        return ""
    return _NORMALIZE_RE.sub(" ", str(s).strip()).lower()
