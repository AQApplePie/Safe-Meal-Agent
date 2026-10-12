"""实现文档摄取基础设施适配。"""

from pathlib import Path
import os
import tempfile
from uuid import UUID
from safemeal.modules.knowledge.contracts.models import UploadedDocumentRecord

import aiofiles  # type: ignore[import-untyped]


# 类说明（业务或基础设施实现类）：LocalUploadStorage
# 作用：实现本地上传文件与元数据存储，封装该组件的业务处理与依赖协作。
class LocalUploadStorage:
    # 方法说明：__init__
    # 作用：初始化本地上传文件与元数据存储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   root（str | Path）：当前访问的目录路径。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, root: str | Path) -> None:
        # 实例属性说明：root
        # 作用：当前访问的目录路径。
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    # 方法说明：_safe_path
    # 作用：校验路径位于上传存储根目录内，防止路径越界。
    # 入参：
    #   relative_path（str）：相对于上传存储根目录的文件路径。
    # 出参：Path；文件或目录路径。
    def _safe_path(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise FileNotFoundError(relative_path)
        return target

    # 方法说明：write
    # 作用：保存上传文件或底层记录的数据内容。
    # 入参：
    #   relative_path（str）：相对于上传存储根目录的文件路径。
    #   content（bytes）：当前文件、消息或证据的正文内容。
    # 出参：Path；文件或目录路径。
    async def write(self, relative_path: str, content: bytes) -> Path:
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as file_handle:
            await file_handle.write(content)
        return target

    # 方法说明：resolve
    # 作用：在本地上传文件与元数据存储中合并并解析当前输入的业务要求。
    # 入参：
    #   relative_path（str）：相对于上传存储根目录的文件路径。
    # 出参：Path；文件或目录路径。
    def resolve(self, relative_path: str) -> Path:
        target = self._safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(relative_path)
        return target

    # 方法说明：find_by_prefix
    # 作用：按名称前缀查询候选记录。
    # 入参：
    #   prefix（str）：待匹配的名称或键前缀。
    # 出参：Path | None；文件或目录路径或None（未取得结果）。
    def find_by_prefix(self, prefix: str) -> Path | None:
        for path in self.root.rglob(f"{prefix}*"):
            if path.is_file():
                return path
        return None

    # 方法说明：delete
    # 作用：删除当前存储中的指定记录。
    # 入参：
    #   path（Path）：本次读取或写入的路径。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def delete(self, path: Path) -> None:
        target = path.resolve()
        if self.root not in target.parents or not target.is_file():
            raise FileNotFoundError(path)
        target.unlink()

    # 方法说明：_record_path
    # 作用：生成上传记录元数据文件的安全路径。
    # 入参：
    #   file_id（str）：上传文件标识。
    # 出参：Path；文件或目录路径。
    def _record_path(self, file_id: str) -> Path:
        return self._safe_path(f".documents/{UUID(file_id)}.json")

    # 方法说明：save_record
    # 作用：持久化上传记录的元数据。
    # 入参：
    #   record（UploadedDocumentRecord）：上传文件持久元数据记录。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def save_record(self, record: UploadedDocumentRecord) -> None:
        target = self._record_path(str(record.file.file_id))
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", dir=target.parent, delete=False, encoding="utf-8"
        ) as handle:
            temporary = Path(handle.name)
            try:
                handle.write(record.model_dump_json())
                handle.flush()
                os.fsync(handle.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    # 方法说明：get_record
    # 作用：按上传标识读取文件元数据记录。
    # 入参：
    #   file_id（str）：上传文件标识。
    # 出参：UploadedDocumentRecord | None；上传文件持久元数据记录或None（未取得结果）。
    def get_record(self, file_id: str) -> UploadedDocumentRecord | None:
        try:
            path = self._record_path(file_id)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return UploadedDocumentRecord.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    # 方法说明：list_records
    # 作用：列出满足条件的上传元数据记录。
    # 入参：
    #   tenant_id（str）：可信租户标识，用于业务数据隔离。
    # 出参：list[UploadedDocumentRecord]；上传文件持久元数据记录的集合。
    def list_records(self, tenant_id: str) -> list[UploadedDocumentRecord]:
        records = [
            UploadedDocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in (self.root / ".documents").glob("*.json")
        ]
        return [record for record in records if record.tenant_id == tenant_id]

    # 方法说明：delete_record
    # 作用：删除上传文件的持久元数据记录。
    # 入参：
    #   file_id（str）：上传文件标识。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def delete_record(self, file_id: str) -> None:
        self._record_path(file_id).unlink(missing_ok=True)
