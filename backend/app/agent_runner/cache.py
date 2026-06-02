"""KGStore + Agent 实例的 LRU 缓存（按 document_id）。

直接 import graphrag_pipeline（同 venv），不通过 subprocess。
"""
from __future__ import annotations
import sys
from collections import OrderedDict
from pathlib import Path

from app.config import AGENT_LRU_SIZE, BASE_DIR

# 确保 graphrag_pipeline 可 import（同 venv 安装）
_gp_path = str(BASE_DIR.parent)
if _gp_path not in sys.path:
    sys.path.insert(0, _gp_path)

try:
    from graphrag_pipeline.kg_store import KGStore
    from graphrag_pipeline.agent import build_agent
    _PIPELINE_AVAILABLE = True
except ImportError:
    _PIPELINE_AVAILABLE = False
    KGStore = None  # type: ignore
    build_agent = None  # type: ignore


class AgentRunner:
    def __init__(self, max_size: int = AGENT_LRU_SIZE) -> None:
        self._cache: OrderedDict[str, tuple] = OrderedDict()
        self._max_size = max_size

    def get_or_load(self, document_id: str, kg_json_path: Path):
        if document_id in self._cache:
            cached = self._cache[document_id]
            # 防御：缓存里可能残留 (None, None) 之类的毒值；命中后校验，无效则重建
            if cached and cached[0] is not None and cached[1] is not None:
                self._cache.move_to_end(document_id)
                return cached
            # 毒值，剔除后走重建逻辑
            self._cache.pop(document_id, None)
        if not _PIPELINE_AVAILABLE:
            raise RuntimeError("graphrag_pipeline 未安装，无法加载 Agent")
        store = KGStore.from_json(kg_json_path)
        agent = build_agent(store)
        if store is None or agent is None:
            raise RuntimeError("KGStore 或 Agent 构建失败（返回 None）")
        self._set(document_id, (store, agent))
        return store, agent

    def cache_set(self, document_id: str, store, agent) -> None:
        # 拒绝写入毒值
        if store is None or agent is None:
            return
        self._set(document_id, (store, agent))

    def evict(self, document_id: str) -> None:
        self._cache.pop(document_id, None)

    def _set(self, document_id: str, value: tuple) -> None:
        self._cache[document_id] = value
        self._cache.move_to_end(document_id)
        while len(self._cache) > self._max_size:
            self._cache.popitem(last=False)


# 全局单例
agent_runner = AgentRunner()
