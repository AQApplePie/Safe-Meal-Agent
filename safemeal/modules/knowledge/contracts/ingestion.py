"""定义跨层传递的稳定数据契约。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field

ChunkStrategyName = Literal["auto", "recursive", "semantic"]


# 类说明（数据契约类）：IngestionJob
# 作用：描述异步文档摄取任务的结构、类型及可校验字段。
class IngestionJob(BaseModel):
    # 字段说明：job_id
    # 作用：文档摄取任务标识。
    # 类型：str。
    # 配置：默认值工厂（每次创建独立对象）=lambda: uuid4().hex。
    job_id: str = Field(default_factory=lambda: uuid4().hex)
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：filename
    # 作用：上传文件的原始名称。
    # 类型：str。
    filename: str
    # 字段说明：content_hex
    # 作用：二进制文件内容的十六进制表示，便于通过 JSON 传递。
    # 类型：str。
    content_hex: str
    # 字段说明：chunk_strategy
    # 作用：请求使用的文档分块策略。
    # 类型：ChunkStrategyName。
    # 初始值：'auto'。
    # 取值说明：
    #   auto：自动选择的模式。
    #   recursive：递归切分。
    #   semantic：语义匹配或切分。
    chunk_strategy: ChunkStrategyName = "auto"
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['queued', 'running', 'succeeded', 'failed']。
    # 初始值：'queued'。
    # 取值说明：
    #   queued：已排队，尚未开始处理。
    #   running：正在运行。
    #   succeeded：执行成功。
    #   failed：处理失败。
    status: Literal["queued", "running", "succeeded", "failed"] = "queued"
    # 字段说明：error
    # 作用：当前操作的错误信息。
    # 类型：str | None。
    # 初始值：None。
    error: str | None = None
    # 字段说明：result
    # 作用：当前已获得的操作或工具结果。
    # 类型：dict[str, object] | None。
    # 初始值：None。
    result: dict[str, object] | None = None
    # 字段说明：created_at
    # 作用：记录创建时间，用于排序和审计。
    # 类型：str。
    # 配置：默认值工厂（每次创建独立对象）=lambda: datetime.now(timezone.utc).isoformat()。
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # 方法说明：create
    # 作用：通过异步文档摄取任务校验并创建新的业务对象。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    #   filename（str）：上传文件的原始名称。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    #   chunk_strategy（ChunkStrategyName）：请求使用的文档分块策略。
    # 出参：'IngestionJob'；异步文档摄取任务。
    @classmethod
    def create(
        cls,
        *,
        tenant_id: str,
        filename: str,
        content: bytes,
        chunk_strategy: ChunkStrategyName,
    ) -> "IngestionJob":
        return cls(
            tenant_id=tenant_id,
            filename=filename,
            content_hex=content.hex(),
            chunk_strategy=chunk_strategy,
        )

    # 方法说明：content
    # 作用：取得当前消息或证据的正文内容。
    # 入参：
    #   无显式入参。
    # 出参：bytes；二进制字节。
    @property
    def content(self) -> bytes:
        return bytes.fromhex(self.content_hex)
