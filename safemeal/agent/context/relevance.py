"""根据当前请求筛选应进入 Agent 上下文的记忆。"""

from collections import Counter
from math import sqrt
import re
from typing import Sequence

from safemeal.shared.types import JsonObject


_FEATURE_PATTERN = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9_]+")


# 方法说明：_features
# 作用：把文本拆成用于记忆相关性计算的词频特征。
# 入参：
#   text（str）：待解析、检索、切分或渲染的文本。
# 出参：Counter[str]；文本词项对应的出现次数。
def _features(text: str) -> Counter[str]:
    normalized = "".join(_FEATURE_PATTERN.findall(text.casefold()))
    features: Counter[str] = Counter(_FEATURE_PATTERN.findall(text.casefold()))
    features.update(
        normalized[index : index + 2] for index in range(len(normalized) - 1)
    )
    return features


# 方法说明：_cosine
# 作用：计算两个特征向量的余弦相似度，零向量按无相似度处理。
# 入参：
#   left（Counter[str]）：参与匹配或相似度计算的两侧输入。
#   right（Counter[str]）：参与匹配或相似度计算的两侧输入。
# 出参：float；两个输入特征的余弦相似度。
def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    denominator = sqrt(sum(value * value for value in left.values())) * sqrt(
        sum(value * value for value in right.values())
    )
    if denominator == 0:
        return 0.0
    return sum(value * right.get(key, 0) for key, value in left.items()) / denominator


# 类说明（业务或基础设施实现类）：MemoryRelevanceSelector
# 作用：保留全部硬安全记忆，并按相关性选择软记忆。
class MemoryRelevanceSelector:
    """保留全部硬安全记忆，并按相关性选择软记忆。"""

    # 字段说明：HARD_TYPES
    # 作用：HARDTYPES，供该组件初始化及运行控制使用。
    # 初始值：{'dietary_allergy', 'dietary_restriction'}。
    HARD_TYPES = {"dietary_allergy", "dietary_restriction"}

    # 方法说明：__init__
    # 作用：初始化长期记忆相关性选择器，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   limit（int）：本次查询或处理的最大条目数；默认值为 20。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, limit: int = 20) -> None:
        # 实例属性说明：limit
        # 作用：本次查询或处理的最大条目数。
        self.limit = limit

    # 方法说明：select
    # 作用：通过长期记忆相关性选择器筛选与当前任务相关的候选信息。
    # 入参：
    #   message（str）：本轮用户消息或问题文本。
    #   memories（Sequence[JsonObject]）：已经加载的用户长期记忆。
    # 出参：list[JsonObject]；JSON 字段映射的集合。
    def select(self, message: str, memories: Sequence[JsonObject]) -> list[JsonObject]:
        query = _features(message)

        # 方法说明：score
        # 作用：计算候选信息与长期记忆相关性选择器当前选择目标的相关性分数。
        # 入参：
        #   memory（JsonObject）：当前处理的长期记忆记录。
        # 出参：tuple[float, float, str]；数值、数值、文本字符串组成的元组。
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

        hard = [m for m in memories if m.get("memory_type") in self.HARD_TYPES]
        soft = [m for m in memories if m.get("memory_type") not in self.HARD_TYPES]
        return hard + sorted(soft, key=score, reverse=True)[: self.limit]


__all__ = ["MemoryRelevanceSelector"]
