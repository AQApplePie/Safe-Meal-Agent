"""Local-filesystem adapter for uploaded files."""

from pathlib import Path

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
