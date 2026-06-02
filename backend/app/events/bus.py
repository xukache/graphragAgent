"""进程内 EventBus：每个 task_id 对应一个 asyncio.Queue。"""
from __future__ import annotations
import asyncio
from typing import AsyncIterator

_SENTINEL = object()


class EventBus:
    def __init__(self) -> None:
        self._queues: dict[str, list[asyncio.Queue]] = {}

    def publish(self, task_id: str, event: dict) -> None:
        for q in self._queues.get(task_id, []):
            q.put_nowait(event)

    def close(self, task_id: str) -> None:
        """任务终态时推 sentinel，关闭所有订阅者。"""
        for q in self._queues.get(task_id, []):
            q.put_nowait(_SENTINEL)

    async def subscribe(self, task_id: str) -> AsyncIterator[dict]:
        q: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(task_id, []).append(q)
        try:
            while True:
                item = await q.get()
                if item is _SENTINEL:
                    break
                yield item
        finally:
            self._queues.get(task_id, []).remove(q)
            if not self._queues.get(task_id):
                self._queues.pop(task_id, None)


# 全局单例
event_bus = EventBus()
