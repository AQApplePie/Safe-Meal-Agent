import pytest
from safemeal.application.contracts.upload.models import ParsedDocument
from safemeal.application.service.upload.file_upload_service import (
    FileUploadService,
    UploadNotFoundError,
)
from safemeal.application.service.upload.uploaded_document_ingestion_service import (
    UploadedDocumentIngestionService,
)
from safemeal.application.service.knowledge.document_knowledge_service import (
    DocumentKnowledgeService,
)
from safemeal.application.exceptions import ExternalServiceError
from safemeal.infrastructure.ingestion.local_upload_storage import LocalUploadStorage


class Parser:
    def parse(self, name, content):
        return ParsedDocument(content.decode(), "text")


class Knowledge:
    def __init__(self):
        self.ids = set()
        self.delete_ok = True

    async def ingest_text(self, text, *, metadata, **kwargs):
        self.ids.add(metadata["document_id"])
        return {"add_count": 1}

    async def delete_document(self, document_id):
        if self.delete_ok:
            self.ids.discard(document_id)
        return self.delete_ok


@pytest.mark.asyncio
async def test_file_ownership_and_retryable_index_first_deletion(tmp_path):
    files = FileUploadService(LocalUploadStorage(tmp_path), 1000)
    knowledge = Knowledge()
    ingestion = UploadedDocumentIngestionService(
        file_upload_service=files,
        document_parser=Parser(),
        document_knowledge=knowledge,
    )
    result = await ingestion.ingest(
        original_filename="recipe.txt", content=b"potato", tenant_id="one"
    )
    file_id = result.file.file_id
    assert result.file.file_url == f"/api/v1/knowledge/files/{file_id}/content"
    assert files.list_documents("one")[0].status == "indexed"
    assert files.list_documents("two") == []
    with pytest.raises(UploadNotFoundError):
        await ingestion.delete(file_id=file_id, tenant_id="two")
    knowledge.delete_ok = False
    with pytest.raises(ExternalServiceError):
        await ingestion.delete(file_id=file_id, tenant_id="one")
    assert files.resolve(result.file.filename).exists()
    assert files.get_document(file_id, "one").status == "deleting"
    knowledge.delete_ok = True
    await ingestion.delete(file_id=file_id, tenant_id="one")
    assert not knowledge.ids
    assert files.list_documents("one") == []
    with pytest.raises(UploadNotFoundError):
        files.resolve(result.file.filename)


@pytest.mark.asyncio
async def test_failed_parse_remains_owned_and_can_be_cleaned(tmp_path):
    class BrokenParser:
        def parse(self, *args):
            raise ValueError("bad document")

    files = FileUploadService(LocalUploadStorage(tmp_path), 1000)
    ingestion = UploadedDocumentIngestionService(
        file_upload_service=files,
        document_parser=BrokenParser(),
        document_knowledge=Knowledge(),
    )
    with pytest.raises(ValueError):
        await ingestion.ingest(
            original_filename="broken.txt", content=b"data", tenant_id="one"
        )
    record = files.list_documents("one")[0]
    assert record.status == "failed"
    await ingestion.delete(file_id=record.file.file_id, tenant_id="one")
    assert not files.list_documents("one")


@pytest.mark.asyncio
async def test_lexical_cleanup_failure_is_not_reported_as_success():
    from types import SimpleNamespace

    class Repository:
        def __init__(self, ok):
            self.ok = ok
            self.calls = []

        def delete_documents(self, ids):
            self.calls.append(ids)
            return self.ok

    vector, lexical = Repository(True), Repository(False)
    service = SimpleNamespace(vector_repository=vector, lexical_repository=lexical)
    assert not await DocumentKnowledgeService.delete_document(service, "one:file")
    assert vector.calls == lexical.calls == [["one:file"]]
