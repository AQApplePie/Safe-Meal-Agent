"""实现聊天工作流中的对应职责。"""

from __future__ import annotations
from safemeal.agent.contracts.workflow.models import ConversationContextResult

import re
from typing import Sequence

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)
from safemeal.shared.types import JsonObject


_TOKEN_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


# 方法说明：estimate_tokens
# 作用：估算文本或结构化对象的 Token 数，供上下文预算裁剪使用。
# 入参：
#   text（str）：待解析、检索、切分或渲染的文本。
# 出参：int；用于上下文裁剪的估算 Token 数。
def estimate_tokens(text: str) -> int:

    pieces = _TOKEN_PATTERN.findall(text)
    if not pieces:
        return max(1, len(text) // 3)
    return max(
        1, sum(1 if len(piece) == 1 else (len(piece) + 3) // 4 for piece in pieces)
    )


# 类说明（业务或基础设施实现类）：ConversationContextWindow
# 作用：实现历史消息裁剪与摘要窗口，封装该组件的业务处理与依赖协作。
class ConversationContextWindow:
    # 方法说明：__init__
    # 作用：初始化历史消息裁剪与摘要窗口，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   token_budget（int）：上下文允许使用的 Token 预算。
    #   response_token_reserve（int）：为最终回答预留的 Token 预算。
    #   minimum_recent_messages（int）：摘要裁剪后至少保留的近期消息数；默认值为 4。
    #   summary_max_chars（int）：历史摘要的最大字符数；默认值为 2000。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        # 实例属性说明：token_budget
        # 作用：上下文允许使用的 Token 预算。
        self.token_budget = token_budget
        # 实例属性说明：response_token_reserve
        # 作用：为最终回答预留的 Token 预算。
        self.response_token_reserve = response_token_reserve
        # 实例属性说明：minimum_recent_messages
        # 作用：摘要裁剪后至少保留的近期消息数。
        self.minimum_recent_messages = minimum_recent_messages
        # 实例属性说明：summary_max_chars
        # 作用：历史摘要的最大字符数。
        self.summary_max_chars = summary_max_chars

    # 方法说明：prepare
    # 作用：为当前请求准备上下文与运行依赖。
    # 入参：
    #   history（Sequence[dict[str, str]]）：已加载的近期对话上下文。
    #   current_message（str）：本轮用户消息或问题文本。
    # 出参：ConversationContextResult；历史对话上下文结果。
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

    # 方法说明：_summarize
    # 作用：在字符预算内压缩较早历史消息为对话摘要。
    # 入参：
    #   messages（Sequence[dict[str, str]]）：按顺序组织的历史对话消息。
    # 出参：str；符合长度限制的摘要文本。
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
