"""实现文档摄取基础设施适配。"""

from pathlib import Path
import os
import tempfile
from uuid import UUID
from safemeal.modules.knowledge.contracts.models import UploadedDocumentRecord

import aiofiles  # type: ignore[import-untyped]


class LocalUploadStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _safe_path(self, relative_path: str) -> Path:
        target = (self.root / relative_path).resolve()
        if target != self.root and self.root not in target.parents:
            raise FileNotFoundError(relative_path)
        return target

    async def write(self, relative_path: str, content: bytes) -> Path:
        target = self._safe_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(target, "wb") as file_handle:
            await file_handle.write(content)
        return target

    def resolve(self, relative_path: str) -> Path:
        target = self._safe_path(relative_path)
        if not target.is_file():
            raise FileNotFoundError(relative_path)
        return target

    def find_by_prefix(self, prefix: str) -> Path | None:
        for path in self.root.rglob(f"{prefix}*"):
            if path.is_file():
                return path
        return None

    def delete(self, path: Path) -> None:
        target = path.resolve()
        if self.root not in target.parents or not target.is_file():
            raise FileNotFoundError(path)
        target.unlink()

    def _record_path(self, file_id: str) -> Path:
        return self._safe_path(f".documents/{UUID(file_id)}.json")

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

    def list_records(self, tenant_id: str) -> list[UploadedDocumentRecord]:
        records = [
            UploadedDocumentRecord.model_validate_json(path.read_text(encoding="utf-8"))
            for path in (self.root / ".documents").glob("*.json")
        ]
        return [record for record in records if record.tenant_id == tenant_id]

    def delete_record(self, file_id: str) -> None:
        self._record_path(file_id).unlink(missing_ok=True)
