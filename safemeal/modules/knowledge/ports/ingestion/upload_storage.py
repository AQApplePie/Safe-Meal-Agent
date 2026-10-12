"""定义应用层依赖的能力端口。"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from safemeal.modules.knowledge.contracts.models import UploadedDocumentRecord


# 类说明（接口类）：UploadStorage
# 作用：定义上传文件与元数据存储接口的能力契约，供应用层与具体实现解耦。
class UploadStorage(Protocol):
    # 方法说明：write
    # 作用：保存上传文件或底层记录的数据内容。
    # 入参：
    #   relative_path（str）：相对于上传存储根目录的文件路径。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    # 出参：Path；文件或目录路径。
    async def write(self, relative_path: str, content: bytes) -> Path: ...

    # 方法说明：resolve
    # 作用：在上传文件与元数据存储接口中合并并解析当前输入的业务要求。
    # 入参：
    #   relative_path（str）：相对于上传存储根目录的文件路径。
    # 出参：Path；文件或目录路径。
    def resolve(self, relative_path: str) -> Path: ...

    # 方法说明：find_by_prefix
    # 作用：按名称前缀查询候选记录。
    # 入参：
    #   prefix（str）：待匹配的名称或键前缀。
    # 出参：Path | None；文件或目录路径或None（未取得结果）。
    def find_by_prefix(self, prefix: str) -> Path | None: ...

    # 方法说明：delete
    # 作用：删除当前存储中的指定记录。
    # 入参：
    #   path（Path）：本次读取或写入的路径。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def delete(self, path: Path) -> None: ...

    # 方法说明：save_record
    # 作用：持久化上传记录的元数据。
    # 入参：
    #   record（UploadedDocumentRecord）：上传文件持久元数据记录。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def save_record(self, record: UploadedDocumentRecord) -> None: ...

    # 方法说明：get_record
    # 作用：按上传标识读取文件元数据记录。
    # 入参：
    #   file_id（str）：上传文件标识。
    # 出参：UploadedDocumentRecord | None；上传文件持久元数据记录或None（未取得结果）。
    def get_record(self, file_id: str) -> UploadedDocumentRecord | None: ...

    # 方法说明：list_records
    # 作用：列出满足条件的上传元数据记录。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：list[UploadedDocumentRecord]；上传文件持久元数据记录的集合。
    def list_records(self, tenant_id: str) -> list[UploadedDocumentRecord]: ...

    # 方法说明：delete_record
    # 作用：删除上传文件的持久元数据记录。
    # 入参：
    #   file_id（str）：上传文件标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def delete_record(self, file_id: str) -> None: ...
