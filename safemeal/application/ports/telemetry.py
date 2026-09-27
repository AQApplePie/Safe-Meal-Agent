from typing import Protocol
from safemeal.shared.types import JsonObject


class TraceExporter(Protocol):
    async def export(self, trace: JsonObject) -> None: ...
