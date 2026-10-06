"""实现持久化基础设施适配。"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from threading import RLock
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.serde.types import TASKS


class SqliteCheckpointSaver(BaseCheckpointSaver[str]):

    def __init__(self, path: str | Path, *, serde=None) -> None:
        super().__init__(serde=serde)
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL, parent_checkpoint_id TEXT,
                    checkpoint_type TEXT NOT NULL, checkpoint BLOB NOT NULL,
                    metadata_type TEXT NOT NULL, metadata BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                );
                CREATE TABLE IF NOT EXISTS checkpoint_writes (
                    thread_id TEXT NOT NULL, checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    write_index INTEGER NOT NULL, channel TEXT NOT NULL,
                    value_type TEXT NOT NULL, value BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_index)
                );
                CREATE INDEX IF NOT EXISTS ix_checkpoints_latest
                ON checkpoints(thread_id, checkpoint_ns, checkpoint_id DESC);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=30000")
        return connection

    def _load_tuple(self, row: sqlite3.Row) -> CheckpointTuple:
        thread_id = str(row["thread_id"])
        namespace = str(row["checkpoint_ns"])
        checkpoint_id = str(row["checkpoint_id"])
        parent_id = row["parent_checkpoint_id"]
        with self._connect() as connection:
            writes = connection.execute(
                """SELECT task_id, channel, value_type, value FROM checkpoint_writes
                   WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?
                   ORDER BY task_id, write_index""",
                (thread_id, namespace, checkpoint_id),
            ).fetchall()
            sends = (
                connection.execute(
                    """SELECT value_type, value FROM checkpoint_writes
                       WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?
                         AND channel=? ORDER BY task_id, write_index""",
                    (thread_id, namespace, parent_id, TASKS),
                ).fetchall()
                if parent_id
                else []
            )
        checkpoint = self.serde.loads_typed(
            (str(row["checkpoint_type"]), bytes(row["checkpoint"]))
        )
        checkpoint["pending_sends"] = [
            self.serde.loads_typed((str(item["value_type"]), bytes(item["value"])))
            for item in sends
        ]
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": namespace,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=self.serde.loads_typed(
                (str(row["metadata_type"]), bytes(row["metadata"]))
            ),
            parent_config=(
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": namespace,
                        "checkpoint_id": str(parent_id),
                    }
                }
                if parent_id
                else None
            ),
            pending_writes=[
                (
                    str(item["task_id"]),
                    str(item["channel"]),
                    self.serde.loads_typed(
                        (str(item["value_type"]), bytes(item["value"]))
                    ),
                )
                for item in writes
            ],
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        checkpoint_id = get_checkpoint_id(config)
        query = "SELECT * FROM checkpoints WHERE thread_id=? AND checkpoint_ns=? "
        query += (
            "AND checkpoint_id=?"
            if checkpoint_id
            else "ORDER BY checkpoint_id DESC LIMIT 1"
        )
        params = (
            (thread_id, namespace, checkpoint_id)
            if checkpoint_id
            else (thread_id, namespace)
        )
        with self._lock, self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return self._load_tuple(row) if row else None

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        clauses: list[str] = []
        params: list[object] = []
        if config:
            clauses.append("thread_id=?")
            params.append(str(config["configurable"]["thread_id"]))
            if "checkpoint_ns" in config["configurable"]:
                clauses.append("checkpoint_ns=?")
                params.append(str(config["configurable"]["checkpoint_ns"]))
            if checkpoint_id := get_checkpoint_id(config):
                clauses.append("checkpoint_id=?")
                params.append(checkpoint_id)
        if before and (before_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id<?")
            params.append(before_id)
        sql = "SELECT * FROM checkpoints"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY checkpoint_id DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self._lock, self._connect() as connection:
            rows = connection.execute(sql, params).fetchall()
        for row in rows:
            item = self._load_tuple(row)
            if not filter or all(item.metadata.get(k) == v for k, v in filter.items()):
                yield item

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        del new_versions
        saved = {
            key: value for key, value in checkpoint.items() if key != "pending_sends"
        }
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(saved)
        metadata_type, metadata_blob = self.serde.dumps_typed(metadata)
        with self._lock, self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    thread_id,
                    namespace,
                    checkpoint["id"],
                    configurable.get("checkpoint_id"),
                    checkpoint_type,
                    checkpoint_blob,
                    metadata_type,
                    metadata_blob,
                ),
            )
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": namespace,
                "checkpoint_id": checkpoint["id"],
            }
        }

    def put_writes(
        self, config: RunnableConfig, writes: Sequence[tuple[str, Any]], task_id: str
    ) -> None:
        configurable = config["configurable"]
        rows = []
        for index, (channel, value) in enumerate(writes):
            value_type, value_blob = self.serde.dumps_typed(value)
            rows.append(
                (
                    str(configurable["thread_id"]),
                    str(configurable.get("checkpoint_ns", "")),
                    str(configurable["checkpoint_id"]),
                    task_id,
                    WRITES_IDX_MAP.get(channel, index),
                    channel,
                    value_type,
                    value_blob,
                )
            )
        with self._lock, self._connect() as connection:
            connection.executemany(
                "INSERT OR IGNORE INTO checkpoint_writes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                rows,
            )

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await asyncio.to_thread(self.get_tuple, config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        items = await asyncio.to_thread(
            lambda: list(self.list(config, filter=filter, before=before, limit=limit))
        )
        for item in items:
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return await asyncio.to_thread(
            self.put, config, checkpoint, metadata, new_versions
        )

    async def aput_writes(
        self, config: RunnableConfig, writes: Sequence[tuple[str, Any]], task_id: str
    ) -> None:
        await asyncio.to_thread(self.put_writes, config, writes, task_id)

    def get_next_version(self, current: str | None, channel: Any) -> str:
        del channel
        number = int(current.split(".", 1)[0]) if current else 0
        return f"{number + 1:032}.0"


__all__ = ["SqliteCheckpointSaver"]
