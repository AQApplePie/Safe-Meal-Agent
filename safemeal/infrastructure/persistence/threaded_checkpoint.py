"""Expose synchronous database checkpointers to an async LangGraph runner."""

from __future__ import annotations
import asyncio
from inspect import signature
from langgraph.checkpoint.base import BaseCheckpointSaver


class ThreadedCheckpointSaver(BaseCheckpointSaver):
    """Keep synchronous PostgreSQL checkpoint I/O off the event loop."""

    def __init__(self, delegate: BaseCheckpointSaver):
        super().__init__(serde=delegate.serde)
        self.delegate = delegate
        self._supports_task_path = (
            "task_path" in signature(delegate.put_writes).parameters
        )

    @property
    def config_specs(self):
        return self.delegate.config_specs

    def get_tuple(self, config):
        return self.delegate.get_tuple(config)

    def list(self, config, *, filter=None, before=None, limit=None):
        return self.delegate.list(config, filter=filter, before=before, limit=limit)

    def put(self, config, checkpoint, metadata, new_versions):
        return self.delegate.put(config, checkpoint, metadata, new_versions)

    def put_writes(self, config, writes, task_id, task_path=""):
        if self._supports_task_path:
            writer = getattr(self.delegate, "put_writes")
            return writer(config, writes, task_id, task_path=task_path)
        return self.delegate.put_writes(config, writes, task_id)

    def get_next_version(self, current, channel):
        return self.delegate.get_next_version(current, channel)

    async def aget_tuple(self, config):
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(self, config, *, filter=None, before=None, limit=None):
        rows = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for row in rows:
            yield row

    async def aput(self, config, checkpoint, metadata, new_versions):
        return await asyncio.to_thread(
            self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(self, config, writes, task_id, task_path=""):
        await asyncio.to_thread(self.put_writes, config, writes, task_id, task_path)
