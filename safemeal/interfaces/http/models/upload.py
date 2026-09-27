"""HTTP-safe upload response schemas."""

from pydantic import BaseModel

from safemeal.application.contracts.upload.models import UploadSaveResult


class UploadResponse(BaseModel):
    success: bool
    filename: str
    original_name: str
    size: int
    file_type: str
    file_id: str | None = None
    file_url: str | None = None

    @classmethod
    def from_result(cls, result: UploadSaveResult) -> "UploadResponse":
        return cls(**result.model_dump(exclude={"file_path"}))


__all__ = ["UploadResponse"]
