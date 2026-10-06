from __future__ import annotations
from dataclasses import dataclass
from typing import Literal
from pydantic import BaseModel, Field
from safemeal.shared.types import JsonObject


class UploadSaveResult(BaseModel):
    """文档保存后的应用层结果。"""

    success: bool = Field(description="是否保存成功。")
    filename: str = Field(description="服务端保存文件名。")
    original_name: str = Field(description="用户上传的原始文件名。")
    size: int = Field(description="文件大小，单位字节。")
    file_path: str = Field(description="服务端存储路径。")
    file_type: str = Field(description="文件扩展名。")
    file_id: str | None = Field(default=None, description="普通文件 ID。")
    file_url: str | None = Field(default=None, description="普通文件访问 URL。")


class DocumentIngestionResult(BaseModel):

    success: bool
    file: UploadSaveResult
    ingestion: JsonObject
    parser: str
    checksum: str


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    text: str
    parser: str


class UploadedDocumentRecord(BaseModel):

    file: UploadSaveResult
    tenant_id: str
    document_id: str
    status: Literal["processing", "indexed", "failed", "deleting"] = "processing"
