"""本地 JSONL 线上失败队列适配器。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import Lock
from typing import Optional

from SafeMealAgent.back.shared.contracts.feedback import FailureSample
from SafeMealAgent.back.shared.types import JsonObject

try:  # Unix 本地部署用文件锁覆盖多 worker；其他平台仍有进程级锁和 O_APPEND。
    import fcntl
except ImportError:  # pragma: no cover - 项目生产环境为 Linux/macOS
    fcntl = None  # type: ignore[assignment]


_LOCK_REGISTRY_GUARD = Lock()
_PATH_LOCKS: dict[Path, Lock] = {}


def _shared_path_lock(path: Path) -> Lock:
    """同一规范化文件在全进程内始终复用同一把锁。"""

    canonical = path.resolve(strict=False)
    with _LOCK_REGISTRY_GUARD:
        lock = _PATH_LOCKS.get(canonical)
        if lock is None:
            lock = Lock()
            _PATH_LOCKS[canonical] = lock
        return lock


def _trim(value: Optional[str], limit: int) -> str:
    """清理用户文本并限制持久化长度。"""

    return (value or "").strip()[:limit]


def _trace_summary(trace: JsonObject) -> JsonObject:
    """生成不含完整 Prompt 和数据库结果的诊断摘要。"""

    tool_calls = trace.get("tool_calls")
    model_calls = trace.get("model_calls")
    safe_tool_calls = tool_calls if isinstance(tool_calls, list) else []
    safe_model_calls = model_calls if isinstance(model_calls, list) else []
    return {
        "run_id": trace.get("run_id"),
        "status": trace.get("status"),
        "iterations": trace.get("iterations"),
        "total_latency_ms": trace.get("total_latency_ms"),
        "error": _trim(str(trace.get("error") or ""), 2_000),
        "tools": [
            {
                "tool_name": item.get("tool_name"),
                "arguments_valid": item.get("arguments_valid"),
                "ok": item.get("ok"),
                "error": _trim(str(item.get("error") or ""), 1_000),
            }
            for item in safe_tool_calls[:20]
            if isinstance(item, dict)
        ],
        "model_errors": [
            {
                "stage": item.get("stage"),
                "model": item.get("model"),
                "error": _trim(str(item.get("error") or ""), 1_000),
            }
            for item in safe_model_calls
            if isinstance(item, dict) and item.get("error")
        ][:10],
    }


class JsonlFailureCollector:
    """把线上失败追加到本地 JSONL review queue。

    多副本生产部署应实现同一个 FailureCollector 端口，改用数据库或消息队列。
    """

    def __init__(self, queue_path: str | Path) -> None:
        """初始化适配器。

        Args:
            queue_path: 追加写入的 JSONL 文件路径。
        """

        self.queue_path = Path(queue_path).resolve(strict=False)
        self._lock = _shared_path_lock(self.queue_path)

    def _append(self, sample: FailureSample) -> FailureSample:
        """以单行 JSON 原子地追加样本。"""

        line = json.dumps(sample.model_dump(mode="json"), ensure_ascii=False)
        payload = (line + "\n").encode("utf-8")
        with self._lock:
            self.queue_path.parent.mkdir(parents=True, exist_ok=True)
            flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            descriptor = os.open(self.queue_path, flags, 0o600)
            try:
                if fcntl is not None:
                    fcntl.flock(descriptor, fcntl.LOCK_EX)
                view = memoryview(payload)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise OSError("追加线上失败样本失败")
                    view = view[written:]
                os.fsync(descriptor)
            finally:
                try:
                    if fcntl is not None:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
                finally:
                    os.close(descriptor)
        return sample

    def record_agent_error(
        self,
        *,
        session_id: str,
        question: str,
        reason: str,
        trace: JsonObject,
    ) -> FailureSample:
        """记录脱敏后的 Agent 异常。"""

        return self._append(
            FailureSample(
                event_type="agent_error",
                session_id=_trim(session_id, 255),
                question=_trim(question, 5_000),
                reason=_trim(reason, 2_000),
                trace_summary=_trace_summary(trace),
            )
        )

    def record_negative_feedback(
        self,
        *,
        session_id: str,
        message_id: str,
        question: str,
        answer: str,
        reason: str,
        corrected_answer: Optional[str] = None,
        metadata: Optional[JsonObject] = None,
    ) -> FailureSample:
        """记录用户负反馈和可选人工纠正答案。"""

        return self._append(
            FailureSample(
                event_type="negative_feedback",
                session_id=_trim(session_id, 255),
                message_id=_trim(message_id, 255),
                question=_trim(question, 5_000),
                answer=_trim(answer, 10_000),
                reason=_trim(reason, 2_000),
                corrected_answer=(
                    _trim(corrected_answer, 10_000) if corrected_answer else None
                ),
                metadata={
                    key: _trim(str(value), 500)
                    for key, value in (metadata or {}).items()
                    if key in {"route", "user_id", "client_version"}
                },
            )
        )
