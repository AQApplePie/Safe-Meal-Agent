"""跨模块通用 JSON 类型与转换工具。

Agent 工具参数、工具结果、Trace 输入输出都需要在 HTTP 和日志中
序列化。这里用 ``JsonValue``/``JsonObject`` 表达“允许动态，但必须是 JSON
友好结构”，避免在核心业务代码里继续裸用动态类型。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, TypeAlias

from pydantic import BaseModel


JsonValue: TypeAlias = Any
"""JSON 值。

JSON 是明确的动态边界。运行时由 ``to_json_value`` 递归压缩并验证；静态层使用
``Any``，避免用 ``object`` 制造大量虚假的安全感和无意义的类型收窄。
"""

JsonObject: TypeAlias = dict[str, JsonValue]
"""JSON 对象。"""


def to_json_value(value: object) -> JsonValue:
    """把外部对象压成 JSON 友好值。

    Args:
        value: 工具、数据库驱动、Pydantic 模型或普通 Python 对象。

    Returns:
        只包含 JSON 原子值、列表、字典的值；不可直接表达的对象降级为字符串。
    """

    if isinstance(value, BaseModel):
        return to_json_value(value.model_dump(mode="json"))
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): to_json_value(item) for key, item in value.items()}
    if isinstance(value, set):
        return [to_json_value(item) for item in sorted(value, key=str)]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [to_json_value(item) for item in value]
    return str(value)


def to_json_object(value: object) -> JsonObject:
    """把对象转换为 JSON 对象；非对象值会包装进 ``value`` 字段。"""

    payload = to_json_value(value)
    if isinstance(payload, dict):
        return {str(key): item for key, item in payload.items()}
    return {"value": payload}


def to_json_object_list(values: Sequence[object]) -> list[JsonObject]:
    """把一组外部记录转换为 JSON 对象列表。"""

    return [to_json_object(value) for value in values]
