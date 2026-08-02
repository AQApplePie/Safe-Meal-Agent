"""Token-budgeted short-term history and relevance-ranked long-term memory."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import sqrt
import re
from typing import Sequence

from safemeal.shared.contracts.common import ConversationHistory
from safemeal.shared.types import JsonObject


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


def estimate_tokens(text: str) -> int:
    """Conservative model-independent estimate for mixed Chinese/English text."""

    pieces = _TOKEN_PATTERN.findall(text)
    if not pieces:
        return max(1, len(text) // 3)
    return max(
        1, sum(1 if len(piece) == 1 else (len(piece) + 3) // 4 for piece in pieces)
    )


def _features(text: str) -> Counter[str]:
    normalized = "".join(_TOKEN_PATTERN.findall(text.casefold()))
    features: Counter[str] = Counter(_TOKEN_PATTERN.findall(text.casefold()))
    features.update(
        normalized[index : index + 2] for index in range(len(normalized) - 1)
    )
    return features


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    denominator = sqrt(sum(value * value for value in left.values())) * sqrt(
        sum(value * value for value in right.values())
    )
    if denominator == 0:
        return 0.0
    return sum(value * right.get(key, 0) for key, value in left.items()) / denominator


@dataclass(frozen=True)
class ConversationMemoryResult:
    history: ConversationHistory
    episodic_memories: list[JsonObject]
    estimated_tokens: int
    summarized_messages: int


class ConversationMemoryManager:
    """Keep recent turns verbatim and compress older turns into one episode."""

    def __init__(
        self,
        *,
        token_budget: int,
        response_token_reserve: int,
        minimum_recent_messages: int = 4,
        summary_max_chars: int = 2_000,
    ) -> None:
        if token_budget <= response_token_reserve:
            raise ValueError("context token budget must exceed response reserve")
        self.token_budget = token_budget
        self.response_token_reserve = response_token_reserve
        self.minimum_recent_messages = minimum_recent_messages
        self.summary_max_chars = summary_max_chars

    def prepare(
        self,
        history: Sequence[dict[str, str]],
        *,
        current_message: str,
    ) -> ConversationMemoryResult:
        available = max(
            1,
            self.token_budget
            - self.response_token_reserve
            - estimate_tokens(current_message),
        )
        selected: list[dict[str, str]] = []
        selected_tokens = 0
        for message in reversed(history):
            content = str(message.get("content") or "").strip()
            if not content:
                continue
            message_tokens = estimate_tokens(content) + 4
            if (
                len(selected) >= self.minimum_recent_messages
                and selected_tokens + message_tokens > available
            ):
                break
            selected.append(
                {"role": str(message.get("role") or "user"), "content": content}
            )
            selected_tokens += message_tokens
        selected.reverse()
        while len(selected) > 1 and selected_tokens > available:
            removed = selected.pop(0)
            selected_tokens -= estimate_tokens(removed["content"]) + 4
        older_count = max(0, len(history) - len(selected))
        episodic: list[JsonObject] = []
        compressed: ConversationHistory = list(selected)
        if older_count:
            older = history[:older_count]
            episode_summary = self._summarize(older)
            summary = episode_summary
            summary_message = {"role": "system", "content": f"较早对话摘要：{summary}"}
            summary_tokens = estimate_tokens(summary_message["content"]) + 4
            while (
                len(selected) > self.minimum_recent_messages
                and selected_tokens + summary_tokens > available
            ):
                removed = selected.pop(0)
                selected_tokens -= estimate_tokens(removed["content"]) + 4
            summary_budget = max(0, available - selected_tokens)
            while len(summary) > 1 and summary_tokens > summary_budget:
                summary = summary[: max(1, len(summary) * 3 // 4)]
                summary_message["content"] = f"较早对话摘要：{summary}"
                summary_tokens = estimate_tokens(summary_message["content"]) + 4
            include_summary = summary_tokens <= summary_budget
            compressed = [summary_message, *selected] if include_summary else selected
            episodic.append(
                {
                    "memory_type": "conversation_episode",
                    "summary": episode_summary,
                    "message_count": older_count,
                    "relevance_basis": "token_budget_compaction",
                }
            )
            if include_summary:
                selected_tokens += summary_tokens
        return ConversationMemoryResult(
            history=compressed,
            episodic_memories=episodic,
            estimated_tokens=selected_tokens + estimate_tokens(current_message),
            summarized_messages=older_count,
        )

    def _summarize(self, messages: Sequence[dict[str, str]]) -> str:
        parts: list[str] = []
        for message in messages:
            role = "用户" if message.get("role") == "user" else "助手"
            content = " ".join(str(message.get("content") or "").split())
            if content:
                parts.append(f"{role}：{content[:240]}")
        summary = "；".join(parts)
        return summary[: self.summary_max_chars]


class MemoryRelevanceSelector:
    """Rank explicit memories by hard-constraint priority and text relevance."""

    HARD_TYPES = {"dietary_allergy", "dietary_restriction"}

    def __init__(self, limit: int = 20) -> None:
        self.limit = limit

    def select(self, message: str, memories: Sequence[JsonObject]) -> list[JsonObject]:
        query = _features(message)

        def score(memory: JsonObject) -> tuple[float, float, str]:
            memory_type = str(memory.get("memory_type") or "")
            text = " ".join(
                str(memory.get(key) or "")
                for key in ("memory_key", "memory_value", "summary", "memory_type")
            )
            relevance = _cosine(query, _features(text))
            confidence = float(memory.get("confidence") or 0.0)
            hard_bonus = 2.0 if memory_type in self.HARD_TYPES else 0.0
            return hard_bonus + relevance, confidence, text

        return sorted(memories, key=score, reverse=True)[: self.limit]


__all__ = [
    "ConversationMemoryManager",
    "ConversationMemoryResult",
    "MemoryRelevanceSelector",
    "estimate_tokens",
]
