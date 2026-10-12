"""定义应用层依赖的能力端口。"""

from __future__ import annotations
from safemeal.modules.knowledge.contracts.models import ParsedDocument

from typing import Protocol


# 类说明（异常类）：DocumentParseError
# 作用：表示上传文档无法转换为可摄取文本。
class DocumentParseError(ValueError):
    """表示上传文档无法转换为可摄取文本。"""


# 类说明（接口类）：DocumentParser
# 作用：定义上传文档解析接口的能力契约，供应用层与具体实现解耦。
class DocumentParser(Protocol):
    # 方法说明：parse
    # 作用：通过上传文档解析接口解析输入并生成结构化结果。
    # 入参：
    #   filename（str）：上传文件的原始名称。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    # 出参：ParsedDocument；上传文件解析后的文档。
    def parse(self, filename: str, content: bytes) -> ParsedDocument: ...


__all__ = ["DocumentParseError", "DocumentParser", "ParsedDocument"]
