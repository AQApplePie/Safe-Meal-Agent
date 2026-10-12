"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias

from safemeal.shared.types import JsonObject


ExtractedMemoryType: TypeAlias = Literal[
    "dietary_allergy",
    "dietary_restriction",
    "taste_dislike",
    "taste_preference",
    "cooking_constraint",
    "cooking_equipment",
    "cooking_time",
    "health_goal",
]


# 类说明（数据契约类）：MemoryCandidate
# 作用：描述待确认的长期记忆候选的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class MemoryCandidate:
    # 字段说明：memory_type
    # 作用：长期记忆类型。
    # 类型：ExtractedMemoryType。
    # 取值说明：
    #   dietary_allergy：持久化过敏记忆。
    #   dietary_restriction：持久化饮食限制记忆。
    #   taste_dislike：持久化口味厌恶记忆。
    #   taste_preference：持久化口味喜好记忆。
    #   cooking_constraint：制作条件约束。
    #   cooking_equipment：可用厨具记忆。
    #   cooking_time：烹饪时间要求记忆。
    #   health_goal：持久化健康目标记忆。
    memory_type: ExtractedMemoryType
    # 字段说明：key
    # 作用：业务缓存键或记录键。
    # 类型：str。
    key: str
    # 字段说明：value
    # 作用：从用户输入中提取的候选记忆事实内容。
    # 类型：str。
    value: str
    # 字段说明：confidence
    # 作用：该记忆事实的置信度，范围为 0 至 1；显式安全约束仍按可信规则处理。
    # 类型：float。
    confidence: float
    # 字段说明：metadata
    # 作用：文档、消息或证据的来源与辅助元数据。
    # 类型：JsonObject | None。
    # 初始值：None。
    metadata: JsonObject | None = None


# 类说明（数据契约类）：MemoryExtractionResult
# 作用：描述长期记忆抽取结果的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class MemoryExtractionResult:
    # 字段说明：candidates
    # 作用：待筛选或待排序的候选集合。
    # 类型：tuple[MemoryCandidate, ...]。
    # 初始值：()。
    candidates: tuple[MemoryCandidate, ...] = ()
    # 字段说明：retracted_dietary_keys
    # 作用：用户明确撤销的饮食记忆键，避免继续应用旧约束。
    # 类型：tuple[str, ...]。
    # 初始值：()。
    retracted_dietary_keys: tuple[str, ...] = ()


__all__ = ["ExtractedMemoryType", "MemoryCandidate", "MemoryExtractionResult"]
