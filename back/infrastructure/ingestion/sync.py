"""Checksum-based incremental source synchronization and periodic scheduler."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from threading import Lock
from time import monotonic

from loguru import logger

from SafeMealAgent.back.application.use_cases.knowledge.chunking import ChunkStrategyName
from SafeMealAgent.back.application.use_cases.knowledge.service import KnowledgeService
from .documents import DocumentParserRegistry
from .connectors import SourceConnectorRegistry, SourceNotFoundError


@dataclass
class SyncState:
    source_uri: str
    document_id: str
    checksum: str
    status: str
    synced_at: str
    error: str | None = None


class JsonSyncStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._lock = Lock()

    def get(self, source_uri: str) -> SyncState | None:
        records = self._read()
        payload = records.get(source_uri)
        return SyncState(**payload) if payload else None

    def put(self, state: SyncState) -> None:
        with self._lock:
            records = self._read()
            records[state.source_uri] = asdict(state)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(self.path.suffix + ".tmp")
            temporary.write_text(
                json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            temporary.replace(self.path)

    def _read(self) -> dict[str, dict]:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))


class SourceSyncService:
    def __init__(
        self,
        connectors: SourceConnectorRegistry,
        knowledge: KnowledgeService,
        state_store: JsonSyncStateStore,
        parsers: DocumentParserRegistry | None = None,
        delete_missing: bool = True,
    ) -> None:
        self.connectors = connectors
        self.knowledge = knowledge
        self.state_store = state_store
        self.parsers = parsers or DocumentParserRegistry()
        self.delete_missing = delete_missing

    async def sync(
        self,
        source_uri: str,
        *,
        force: bool = False,
        chunk_strategy: ChunkStrategyName = "auto",
        delete_missing: bool | None = None,
    ) -> SyncState:
        current = self.state_store.get(source_uri)
        checksum = current.checksum if current else ""
        try:
            fetched = await self.connectors.fetch(source_uri)
            checksum = fetched.checksum
            if (
                current
                and current.status in {"synced", "unchanged"}
                and current.checksum == fetched.checksum
                and not force
            ):
                current.status = "unchanged"
                current.synced_at = datetime.now(timezone.utc).isoformat()
                self.state_store.put(current)
                return current
            document_id = current.document_id if current else fetched.source_id
            parsed = await asyncio.to_thread(
                self.parsers.parse, fetched.filename, fetched.content
            )
            await self.knowledge.ingest_text(
                parsed.text,
                metadata={
                    **fetched.metadata,
                    "document_id": document_id,
                    "checksum": fetched.checksum,
                    "source_uri": source_uri,
                    "parser": parsed.parser,
                },
                chunk_strategy=chunk_strategy,
            )
            state = SyncState(
                source_uri,
                document_id,
                fetched.checksum,
                "synced",
                datetime.now(timezone.utc).isoformat(),
            )
        except SourceNotFoundError as exc:
            should_delete = (
                self.delete_missing if delete_missing is None else delete_missing
            )
            document_id = current.document_id if current else source_uri
            status = "missing"
            if current and should_delete:
                if current.status != "deleted":
                    await self.knowledge.delete_document(document_id)
                status = "deleted"
            state = SyncState(
                source_uri,
                document_id,
                "",
                status,
                datetime.now(timezone.utc).isoformat(),
                None if status == "deleted" else str(exc),
            )
        except Exception as exc:
            document_id = current.document_id if current else source_uri
            state = SyncState(
                source_uri,
                document_id,
                checksum,
                "failed",
                datetime.now(timezone.utc).isoformat(),
                str(exc),
            )
        self.state_store.put(state)
        return state


@dataclass(frozen=True)
class SyncJob:
    source_uri: str
    interval_seconds: float
    chunk_strategy: ChunkStrategyName = "auto"
    delete_missing: bool | None = None

    def __post_init__(self) -> None:
        if self.interval_seconds <= 0:
            raise ValueError("sync interval must be positive")
        if self.chunk_strategy not in {"auto", "recursive", "semantic"}:
            raise ValueError("unsupported sync chunk strategy")


class SyncScheduler:
    def __init__(self, service: SourceSyncService, jobs: list[SyncJob]) -> None:
        self.service = service
        self.jobs = jobs
        self._tasks: list[asyncio.Task[None]] = []

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [asyncio.create_task(self._run(job)) for job in self.jobs]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run(self, job: SyncJob) -> None:
        while True:
            started = monotonic()
            try:
                await self.service.sync(
                    job.source_uri,
                    chunk_strategy=job.chunk_strategy,
                    delete_missing=job.delete_missing,
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "source.sync.job_failed source_uri={} retry_in_seconds={}",
                    job.source_uri,
                    job.interval_seconds,
                )
            remaining = max(0.0, job.interval_seconds - (monotonic() - started))
            await asyncio.sleep(remaining)
