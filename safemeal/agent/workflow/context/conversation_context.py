"""实现聊天工作流中的对应职责。"""

from __future__ import annotations
from safemeal.agent.contracts.workflow.models import ConversationContextResult

import re
from typing import Sequence

from safemeal.modules.conversation.contracts.conversation.models import ConversationHistory
from safemeal.shared.types import JsonObject


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


def estimate_tokens(text: str) -> int:

    pieces = _TOKEN_PATTERN.findall(text)
    if not pieces:
        return max(1, len(text) // 3)
    return max(
        1, sum(1 if len(piece) == 1 else (len(piece) + 3) // 4 for piece in pieces)
    )


class ConversationContextWindow:

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
    ) -> ConversationContextResult:
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
        return ConversationContextResult(
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


__all__ = [
    "ConversationContextResult",
    "ConversationContextWindow",
    "estimate_tokens",
]
