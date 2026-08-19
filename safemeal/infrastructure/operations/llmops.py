"""Optional LLMOps webhook exporter for completed Agent traces."""

from __future__ import annotations

import httpx

from safemeal.shared.types import JsonObject


class LlmOpsExporter:
    def __init__(self, endpoint: str, api_key: str | None = None) -> None:
        self.endpoint = endpoint
        self.api_key = api_key

    async def export(self, trace: JsonObject) -> None:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.post(self.endpoint, json=trace, headers=headers)
            response.raise_for_status()


__all__ = ["LlmOpsExporter"]
