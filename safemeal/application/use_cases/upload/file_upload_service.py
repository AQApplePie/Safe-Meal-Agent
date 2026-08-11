"""文件上传应用服务与输入校验。

上传大小、文件名规范和存储调用由应用层统一编排；具体磁盘或对象存储实现
通过 ``UploadStorage`` 协议注入。
"""

from pathlib import Path
import uuid

from pydantic import BaseModel, Field

from safemeal.application.ports.ingestion.upload_storage import UploadStorage


class UploadError(Exception):
    """上传业务异常基类。"""


class InvalidUploadError(UploadError):
    """文件类型不受支持。"""


class UploadSizeLimitError(UploadError):
    """文件超过大小限制。"""


class UploadNotFoundError(UploadError):
    """目标文件不存在。"""


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


class FileUploadService:
    FILE_TYPES = {
        ".txt",
        ".md",
        ".pdf",
    }

    def __init__(self, storage: UploadStorage, max_size_bytes: int) -> None:
        self.storage = storage
        self.max_size_bytes = max_size_bytes

    async def save(
        self,
        original_filename: str | None,
        content: bytes,
    ) -> UploadSaveResult:
        original_name = Path(original_filename or "upload").name
        if len(original_name) > 255:
            raise InvalidUploadError("文件名过长")
        extension = Path(original_name).suffix.lower()
        if extension not in self.FILE_TYPES:
            supported = ", ".join(sorted(self.FILE_TYPES))
            raise InvalidUploadError(f"不支持的文件类型。支持的类型为: {supported}")
        if len(content) > self.max_size_bytes:
            max_mb = self.max_size_bytes / (1024 * 1024)
            raise UploadSizeLimitError(f"文件太大，最大支持 {max_mb:g} MB")
        if not content:
            raise InvalidUploadError("文件内容不能为空")

        file_id = str(uuid.uuid4())
        filename = f"{file_id}_{original_name}"
        file_path = await self.storage.write(filename, content)
        return UploadSaveResult(
            success=True,
            filename=filename,
            original_name=original_name,
            size=len(content),
            file_path=str(file_path),
            file_type=extension,
            file_id=file_id,
            file_url=f"/api/v1/upload/files/{filename}",
        )

    def resolve(self, filename: str) -> Path:
        safe_name = Path(filename).name
        if safe_name != filename:
            raise UploadNotFoundError("文件不存在")
        try:
            return self.storage.resolve(safe_name)
        except FileNotFoundError as exc:
            raise UploadNotFoundError("文件不存在") from exc

    def delete(self, file_id: str) -> None:
        try:
            uuid.UUID(file_id)
        except ValueError as exc:
            raise UploadNotFoundError("文件不存在") from exc

        file_path = self.storage.find_by_prefix(f"{file_id}_")
        if file_path is None:
            raise UploadNotFoundError("文件不存在")
        self.storage.delete(file_path)
