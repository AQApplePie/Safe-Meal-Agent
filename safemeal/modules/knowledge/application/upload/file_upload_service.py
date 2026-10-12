"""文件上传应用服务与输入校验。

上传大小、文件名规范和存储调用由应用层统一编排；具体磁盘或对象存储实现
通过 ``UploadStorage`` 协议注入。
"""

from safemeal.modules.knowledge.contracts.models import (
    UploadSaveResult,
    UploadedDocumentRecord,
)

from pathlib import Path
import uuid


from safemeal.modules.knowledge.ports.ingestion.upload_storage import UploadStorage


# 类说明（异常类）：UploadError
# 作用：上传业务异常基类。
class UploadError(Exception):
    """上传业务异常基类。"""


# 类说明（异常类）：InvalidUploadError
# 作用：文件类型不受支持。
class InvalidUploadError(UploadError):
    """文件类型不受支持。"""


# 类说明（异常类）：UploadSizeLimitError
# 作用：文件超过大小限制。
class UploadSizeLimitError(UploadError):
    """文件超过大小限制。"""


# 类说明（异常类）：UploadNotFoundError
# 作用：目标文件不存在。
class UploadNotFoundError(UploadError):
    """目标文件不存在。"""


# 类说明（业务或基础设施实现类）：FileUploadService
# 作用：实现文件上传校验与保存服务，封装该组件的业务处理与依赖协作。
class FileUploadService:
    # 字段说明：FILE_TYPES
    # 作用：文件TYPES，供该组件初始化及运行控制使用。
    # 初始值：{'.txt', '.md', '.pdf', '.png', '.jpg', '.jpeg', '.tif', '.tiff'}。
    FILE_TYPES = {
        ".txt",
        ".md",
        ".pdf",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
    }

    # 方法说明：__init__
    # 作用：初始化文件上传校验与保存服务，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   storage（UploadStorage）：上传文件与记录存储接口。
    #   max_size_bytes（int）：允许读取或保存的最大字节数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, storage: UploadStorage, max_size_bytes: int) -> None:
        # 实例属性说明：storage
        # 作用：上传文件与记录存储接口。
        self.storage = storage
        # 实例属性说明：max_size_bytes
        # 作用：允许读取或保存的最大字节数。
        self.max_size_bytes = max_size_bytes

    # 方法说明：save
    # 作用：通过文件上传校验与保存服务保存当前业务结果或运行状态。
    # 入参：
    #   original_filename（str | None）：上传文件的原始名称。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    # 出参：UploadSaveResult；上传文件保存结果。
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
            file_url=f"/api/v1/knowledge/files/{file_id}/content",
        )

    # 方法说明：resolve
    # 作用：在文件上传校验与保存服务中合并并解析当前输入的业务要求。
    # 入参：
    #   filename（str）：上传文件的原始名称。
    # 出参：Path；文件或目录路径。
    def resolve(self, filename: str) -> Path:
        safe_name = Path(filename).name
        if safe_name != filename:
            raise UploadNotFoundError("文件不存在")
        try:
            return self.storage.resolve(safe_name)
        except FileNotFoundError as exc:
            raise UploadNotFoundError("文件不存在") from exc

    # 方法说明：list_documents
    # 作用：分页列出知识检索存储中的文档。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：list[UploadedDocumentRecord]；上传文件持久元数据记录的集合。
    def list_documents(self, tenant_id: str) -> list[UploadedDocumentRecord]:
        return self.storage.list_records(tenant_id)

    # 方法说明：get_document
    # 作用：按标识读取知识文档及其片段信息。
    # 入参：
    #   file_id（str）：上传文件标识。
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：UploadedDocumentRecord；上传文件持久元数据记录。
    def get_document(self, file_id: str, tenant_id: str) -> UploadedDocumentRecord:
        record = self.storage.get_record(file_id)
        if record is None or record.tenant_id != tenant_id:
            raise UploadNotFoundError("文件不存在")
        return record

    # 方法说明：save_document
    # 作用：保存文档片段、向量及相关来源元数据。
    # 入参：
    #   record（UploadedDocumentRecord）：上传文件持久元数据记录。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def save_document(self, record: UploadedDocumentRecord) -> None:
        self.storage.save_record(record)

    # 方法说明：delete_document_file
    # 作用：删除上传文档文件与关联记录。
    # 入参：
    #   record（UploadedDocumentRecord）：上传文件持久元数据记录。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def delete_document_file(self, record: UploadedDocumentRecord) -> None:

        try:
            path = self.resolve(record.file.filename)
        except UploadNotFoundError:
            pass
        else:
            self.storage.delete(path)
        self.storage.delete_record(str(record.file.file_id))
