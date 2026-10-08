def test_identity_chat_and_file_knowledge_routes_remain(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from fastapi import FastAPI
    from safemeal.interfaces import api_router

    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    paths = app.openapi()["paths"]
    assert all(
        path.startswith(("/api/v1/auth/", "/api/v1/chat/", "/api/v1/knowledge/"))
        for path in paths
    )
    assert "/api/v1/auth/register" in paths
    assert "/api/v1/auth/login" in paths
    assert "/api/v1/auth/refresh" in paths
    assert "/api/v1/auth/logout" in paths
    assert "/api/v1/auth/me" in paths
    assert "/api/v1/chat/resume" in paths
    assert "delete" in paths["/api/v1/chat/sessions/{session_id}/messages"]
    assert "delete" in paths["/api/v1/chat/sessions/{session_id}"]
    assert "patch" in paths["/api/v1/chat/memories/{memory_id}"]
    assert "post" not in paths["/api/v1/chat/sessions"]
    assert "post" in paths["/api/v1/knowledge/files"]
    assert "get" in paths["/api/v1/knowledge/files"]
    assert "/api/v1/knowledge/files/async" in paths
    assert "/api/v1/knowledge/ingestion-jobs/{job_id}" in paths
    assert not any("/recipes" in path or "/clear" in path for path in paths)


def test_file_http_api_scopes_metadata_and_download(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.authentication import get_current_principal, Principal
    from safemeal.interfaces.http.dependencies import get_file_upload_service
    from safemeal.modules.knowledge.application.upload.file_upload_service import (
        FileUploadService,
    )
    from safemeal.infrastructure.ingestion.local_upload_storage import (
        LocalUploadStorage,
    )
    from safemeal.modules.knowledge.contracts.models import UploadedDocumentRecord
    import asyncio

    files = FileUploadService(LocalUploadStorage(tmp_path), 100)
    saved = asyncio.run(files.save("recipe.txt", b"potato"))
    files.save_document(
        UploadedDocumentRecord(
            file=saved, tenant_id="one", document_id="one:file", status="indexed"
        )
    )
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_file_upload_service] = lambda: files
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="user", tenant_id="two"
    )
    with TestClient(app) as client:
        assert client.get("/api/v1/knowledge/files").json() == []
        for suffix in ["", "/content"]:
            assert (
                client.get(
                    f"/api/v1/knowledge/files/{saved.file_id}{suffix}"
                ).status_code
                == 404
            )
        app.dependency_overrides[get_current_principal] = lambda: Principal(
            subject="user", tenant_id="one"
        )
        assert client.get(saved.file_url).content == b"potato"
        assert (
            client.get(f"/api/v1/knowledge/files/{saved.file_id}").json()["status"]
            == "indexed"
        )


def test_chat_session_scope_comes_only_from_authenticated_principal(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///:memory:")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from safemeal.interfaces import api_router
    from safemeal.interfaces.http.authentication import Principal, get_current_principal
    from safemeal.interfaces.http.dependencies import get_chat_session_service

    class Sessions:
        seen_user_id: str | None = None

        def list_sessions(self, *, user_id, skip, limit, active_only):
            self.seen_user_id = user_id
            return []

    sessions = Sessions()
    app = FastAPI()
    app.include_router(api_router, prefix="/api/v1")
    app.dependency_overrides[get_chat_session_service] = lambda: sessions
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        subject="account-id", tenant_id="tenant-id"
    )

    with TestClient(app) as client:
        response = client.get(
            "/api/v1/chat/sessions", params={"user_id": "another-user"}
        )

    assert response.status_code == 200
    assert sessions.seen_user_id == "tenant-id:account-id"
