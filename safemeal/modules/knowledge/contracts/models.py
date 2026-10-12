from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, Field
from safemeal.shared.types import JsonObject


# 类说明（数据契约类）：UploadSaveResult
# 作用：文档保存后的应用层结果。
class UploadSaveResult(BaseModel):
    """文档保存后的应用层结果。"""

    # 字段说明：success
    # 作用：是否保存成功。
    # 类型：bool。
    success: bool = Field(description="是否保存成功。")
    # 字段说明：filename
    # 作用：服务端保存文件名。
    # 类型：str。
    filename: str = Field(description="服务端保存文件名。")
    # 字段说明：original_name
    # 作用：用户上传的原始文件名。
    # 类型：str。
    original_name: str = Field(description="用户上传的原始文件名。")
    # 字段说明：size
    # 作用：保存文件的大小，单位为字节。
    # 类型：int。
    size: int = Field(description="文件大小，单位字节。")
    # 字段说明：file_path
    # 作用：服务端存储路径。
    # 类型：str。
    file_path: str = Field(description="服务端存储路径。")
    # 字段说明：file_type
    # 作用：文件扩展名。
    # 类型：str。
    file_type: str = Field(description="文件扩展名。")
    # 字段说明：file_id
    # 作用：普通文件 ID。
    # 类型：str | None。
    # 配置：默认值=None。
    file_id: str | None = Field(default=None, description="普通文件 ID。")
    # 字段说明：file_url
    # 作用：普通文件访问 URL。
    # 类型：str | None。
    # 配置：默认值=None。
    file_url: str | None = Field(default=None, description="普通文件访问 URL。")


# 类说明（数据契约类）：DocumentIngestionResult
# 作用：描述文档摄取结果的结构、类型及可校验字段。
class DocumentIngestionResult(BaseModel):
    # 字段说明：success
    # 作用：本次操作是否成功。
    # 类型：bool。
    success: bool
    # 字段说明：file
    # 作用：待处理的上传文件对象。
    # 类型：UploadSaveResult。
    file: UploadSaveResult
    # 字段说明：ingestion
    # 作用：文档摄取服务或摄取配置。
    # 类型：JsonObject。
    ingestion: JsonObject
    # 字段说明：parser
    # 作用：将原始文档或响应转换为结构化数据的解析器。
    # 类型：str。
    parser: str
    # 字段说明：checksum
    # 作用：文档内容校验摘要，用于判断内容是否相同或已变化。
    # 类型：str。
    checksum: str


# 类说明（数据契约类）：ParsedDocument
# 作用：描述上传文件解析后的文档的结构、类型及可校验字段。
@dataclass(frozen=True, slots=True)
class ParsedDocument:
    # 字段说明：text
    # 作用：待解析、检索、切分或渲染的文本。
    # 类型：str。
    text: str
    # 字段说明：parser
    # 作用：将原始文档或响应转换为结构化数据的解析器。
    # 类型：str。
    parser: str


# 类说明（数据契约类）：UploadedDocumentRecord
# 作用：描述上传文件持久元数据记录的结构、类型及可校验字段。
class UploadedDocumentRecord(BaseModel):
    # 字段说明：file
    # 作用：待处理的上传文件对象。
    # 类型：UploadSaveResult。
    file: UploadSaveResult
    # 字段说明：tenant_id
    # 作用：可信租户标识，用于业务数据隔离。
    # 类型：str。
    tenant_id: str
    # 字段说明：document_id
    # 作用：文档标识。
    # 类型：str。
    document_id: str
    # 字段说明：status
    # 作用：HTTP 状态码或业务状态。
    # 类型：Literal['processing', 'indexed', 'failed', 'deleting']。
    # 初始值：'processing'。
    # 取值说明：
    #   processing：正在处理。
    #   indexed：已经建立索引。
    #   failed：处理失败。
    #   deleting：正在删除。
    status: Literal["processing", "indexed", "failed", "deleting"] = "processing"
