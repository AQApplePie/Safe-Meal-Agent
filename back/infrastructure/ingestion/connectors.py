"""Local, allowlisted HTTP, S3 and Feishu document source connectors."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

import httpx


class SourceNotFoundError(FileNotFoundError):
    """The configured source no longer exists at the upstream system."""


@dataclass(frozen=True)
class FetchedSource:
    source_id: str
    filename: str
    content: bytes
    metadata: dict[str, object] = field(default_factory=dict)

    @property
    def checksum(self) -> str:
        return sha256(self.content).hexdigest()


class SourceConnector(Protocol):
    async def fetch(self, reference: str) -> FetchedSource: ...


class LocalFileConnector:
    def __init__(self, allowed_root: str | Path) -> None:
        self.allowed_root = Path(allowed_root).resolve()

    async def fetch(self, reference: str) -> FetchedSource:
        path = (self.allowed_root / reference).resolve()
        if path != self.allowed_root and self.allowed_root not in path.parents:
            raise ValueError("local source escapes allowed root")
        try:
            content = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError as exc:
            raise SourceNotFoundError(reference) from exc
        return FetchedSource(
            f"local:{reference}", path.name, content, {"path": str(path)}
        )


class HTTPSourceConnector:
    def __init__(
        self,
        allowed_hosts: set[str],
        *,
        timeout: float = 30.0,
        max_bytes: int = 20_000_000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.allowed_hosts = {host.casefold() for host in allowed_hosts}
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.transport = transport

    async def fetch(self, reference: str) -> FetchedSource:
        parsed = urlparse(reference)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("HTTP source must use https")
        if parsed.hostname.casefold() not in self.allowed_hosts:
            raise ValueError("HTTP source host is not allowlisted")
        async with httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=False,
            transport=self.transport,
        ) as client:
            async with client.stream("GET", reference) as response:
                if response.status_code == 404:
                    raise SourceNotFoundError(reference)
                response.raise_for_status()
                chunks = bytearray()
                async for chunk in response.aiter_bytes():
                    chunks.extend(chunk)
                    if len(chunks) > self.max_bytes:
                        raise ValueError("HTTP source exceeds maximum size")
                disposition = response.headers.get("content-disposition", "")
        filename = Path(parsed.path).name or "document.html"
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip(' "')
        return FetchedSource(
            f"http:{reference}", filename, bytes(chunks), {"url": reference}
        )


class S3SourceConnector:
    def __init__(
        self,
        *,
        bucket: str,
        prefix: str = "",
        endpoint_url: str | None = None,
        max_bytes: int = 20_000_000,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self.endpoint_url = endpoint_url
        self.max_bytes = max_bytes
        self.client_factory = client_factory

    async def fetch(self, reference: str) -> FetchedSource:
        key = reference.lstrip("/")
        if self.prefix and not (
            key == self.prefix or key.startswith(self.prefix + "/")
        ):
            raise ValueError("S3 key is outside configured prefix")

        def download() -> bytes:
            if self.client_factory is None:
                try:
                    import boto3
                except ImportError as exc:
                    raise RuntimeError("S3 connector requires boto3") from exc
                client = boto3.client("s3", endpoint_url=self.endpoint_url)
            else:
                client = self.client_factory()
            try:
                response = client.get_object(Bucket=self.bucket, Key=key)
            except Exception as exc:
                error_response = getattr(exc, "response", {}) or {}
                error = error_response.get("Error", {})
                if error.get("Code") in {"404", "NoSuchKey", "NotFound"}:
                    raise SourceNotFoundError(key) from exc
                raise
            if int(response.get("ContentLength") or 0) > self.max_bytes:
                raise ValueError("S3 source exceeds maximum size")
            content = response["Body"].read(self.max_bytes + 1)
            if len(content) > self.max_bytes:
                raise ValueError("S3 source exceeds maximum size")
            return content

        content = await asyncio.to_thread(download)
        return FetchedSource(
            f"s3:{self.bucket}/{key}",
            Path(key).name,
            content,
            {"bucket": self.bucket, "key": key},
        )


class FeishuDocumentConnector:
    BASE_URL = "https://open.feishu.cn/open-apis"

    def __init__(
        self,
        access_token: str,
        *,
        timeout: float = 30.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not access_token:
            raise ValueError("Feishu access token is required")
        self.access_token = access_token
        self.timeout = timeout
        self.transport = transport

    async def fetch(self, reference: str) -> FetchedSource:
        document_id = reference.strip()
        if not document_id or "/" in document_id:
            raise ValueError("invalid Feishu document id")
        headers = {"Authorization": f"Bearer {self.access_token}"}
        async with httpx.AsyncClient(
            timeout=self.timeout, transport=self.transport
        ) as client:
            response = await client.get(
                f"{self.BASE_URL}/docx/v1/documents/{document_id}/raw_content",
                headers=headers,
            )
            if response.status_code == 404:
                raise SourceNotFoundError(document_id)
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in (None, 0):
            raise RuntimeError(f"Feishu API error: {payload.get('msg')}")
        content = str((payload.get("data") or {}).get("content") or "").encode()
        return FetchedSource(
            f"feishu-docx:{document_id}",
            f"{document_id}.txt",
            content,
            {"document_id": document_id, "source_type": "feishu"},
        )


class SourceConnectorRegistry:
    def __init__(self) -> None:
        self._connectors: dict[str, SourceConnector] = {}

    def register(self, scheme: str, connector: SourceConnector) -> None:
        if scheme in self._connectors:
            raise ValueError(f"duplicate source connector: {scheme}")
        self._connectors[scheme] = connector

    async def fetch(self, uri: str) -> FetchedSource:
        scheme, separator, reference = uri.partition("://")
        if not separator or scheme not in self._connectors:
            raise ValueError(f"unsupported source URI: {uri}")
        resolved_reference = (
            f"{scheme}://{reference}" if scheme in {"http", "https"} else reference
        )
        return await self._connectors[scheme].fetch(resolved_reference)


__all__ = [
    "FetchedSource",
    "FeishuDocumentConnector",
    "HTTPSourceConnector",
    "LocalFileConnector",
    "S3SourceConnector",
    "SourceConnector",
    "SourceConnectorRegistry",
    "SourceNotFoundError",
]
