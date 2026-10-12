"""解析近期对话中的菜谱指代。"""

from __future__ import annotations

import re

from safemeal.modules.conversation.contracts.conversation.models import (
    ConversationHistory,
)


_ORDINALS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
_REFERENCE_ONLY = {"这个", "那个", "它", "刚才那个", "刚才的", "具体"}


# 方法说明：recent_recipe_references
# 作用：从最近消息提取可供指代解析的菜谱引用。
# 入参：
#   history（ConversationHistory）：已加载的近期对话上下文。
# 出参：tuple[str, ...]；按近期顺序去重后的菜谱名称元组。
def recent_recipe_references(history: ConversationHistory) -> tuple[str, ...]:

    assistant_turns = [
        item.get("content", "")
        for item in history[-6:]
        if item.get("role") == "assistant"
    ]
    if not assistant_turns:
        return ()
    latest = assistant_turns[-1]
    names = re.findall(r"「([^」]{1,40})」", latest)
    if not names:
        # Deterministic detail renderer uses an unquoted recipe heading.
        heading = re.match(
            r"^([^\n：:]{1,40})的(?:材料|做法|耗时|营养)[：:]", latest.strip()
        )
        if heading:
            names = [heading.group(1)]
    if not names:
        stripped = latest.strip().strip("。！？!?")
        if 1 <= len(stripped) <= 20 and "\n" not in stripped:
            names = [stripped]
    return tuple(dict.fromkeys(name.strip() for name in names if name.strip()))


# 方法说明：resolve_recipe_reference
# 作用：结合历史菜名和本轮指代，识别实际目标菜谱。
# 入参：
#   message（str）：本轮用户消息或问题文本。
#   history（ConversationHistory）：已加载的近期对话上下文。
# 出参：tuple[str | None, str | None]；文本字符串或None（未取得结果）、文本字符串或None（未取得结果）组成的元组。
def resolve_recipe_reference(
    message: str,
    history: ConversationHistory,
) -> tuple[str | None, str | None]:

    candidates = recent_recipe_references(history)
    ordinal = re.search(r"第([一二两三四五六七八九十]|\d{1,2})个", message)
    if ordinal:
        raw = ordinal.group(1)
        index = (int(raw) if raw.isdigit() else _ORDINALS[raw]) - 1
        if 0 <= index < len(candidates):
            return candidates[index], None
        return None, "你指的序号超出了上一轮推荐列表，请告诉我具体菜名。"

    descriptor = re.search(
        r"(?:这个|那个|刚才(?:那个|的)?)(.+?)(?:要|有|怎么|材料|食材|配料|做法|步骤|[?？]|$)",
        message,
    )
    if descriptor:
        fragment = descriptor.group(1).strip("的菜")
        matches = tuple(name for name in candidates if fragment and fragment in name)
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            choices = "、".join(f"「{name}」" for name in matches)
            return None, f"上一轮有多道符合“{fragment}”的菜：{choices}。请说第几个。"

    refers_back = any(
        marker in message
        for marker in ("这个", "那个", "它", "刚才", "具体", "怎么做", "步骤")
    )
    if not refers_back:
        return None, None
    if len(candidates) == 1:
        return candidates[0], None
    if len(candidates) > 1:
        return None, "上一轮有多道菜，请告诉我是第几个，或者直接说菜名。"
    return None, "我还不能确定你指的是哪道菜，请补充菜名。"


# 方法说明：is_reference_only_target
# 作用：判断请求是否仅通过代词或序号引用已有目标。
# 入参：
#   value（str | None）：当前待转换或校验的值。
# 出参：bool；目标是否仅由代词或顺序引用构成。
def is_reference_only_target(value: str | None) -> bool:
    return bool(
        value
        and (
            value.strip() in _REFERENCE_ONLY
            or value.strip().startswith(("这个", "那个", "刚才那个", "刚才的"))
            or re.fullmatch(r"第(?:[一二两三四五六七八九十]|\d{1,2})个", value.strip())
        )
    )


__all__ = [
    "is_reference_only_target",
    "recent_recipe_references",
    "resolve_recipe_reference",
]
