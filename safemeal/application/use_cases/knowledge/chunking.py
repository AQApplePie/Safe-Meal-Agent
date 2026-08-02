"""Document chunking strategies used by the knowledge ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re
from typing import Literal, Mapping, Sequence

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from safemeal.application.ports import Embedder
from safemeal.shared.types import JsonObject


ChunkStrategyName = Literal["auto", "recursive", "semantic"]


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator


class RecursiveChunkStrategy:
    name = "recursive"

    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
            length_function=len,
        )

    def split(self, text: str, metadata: JsonObject) -> list[Document]:
        document = Document(page_content=text, metadata=dict(metadata))
        return self.splitter.split_documents([document]) or [document]


class SemanticChunkStrategy:
    """Split on adjacent-sentence embedding discontinuities.

    The strategy intentionally caps the number of semantic units. Very large
    documents fall back to recursive splitting so one upload cannot cause an
    unbounded embedding request before the normal ingestion embedding call.
    """

    name = "semantic"
    _BOUNDARY = re.compile(r"(?<=[。！？!?；;])|\n{2,}")

    def __init__(
        self,
        *,
        embedder: Embedder,
        recursive: RecursiveChunkStrategy,
        chunk_size: int,
        chunk_overlap: int,
        breakpoint_threshold: float,
        max_segments: int,
    ) -> None:
        self.embedder = embedder
        self.recursive = recursive
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.breakpoint_threshold = breakpoint_threshold
        self.max_segments = max_segments

    def split(self, text: str, metadata: JsonObject) -> list[Document]:
        units = self._units(text, metadata)
        if len(units) <= 1 or len(units) > self.max_segments:
            return self.recursive.split(text, metadata)

        vectors = self.embedder.embed_documents(units)
        if len(vectors) != len(units):
            return self.recursive.split(text, metadata)

        groups: list[str] = []
        current = units[0]
        for index in range(1, len(units)):
            unit = units[index]
            similarity = _cosine(vectors[index - 1], vectors[index])
            size_boundary = len(current) + 1 + len(unit) > self.chunk_size
            semantic_boundary = similarity < self.breakpoint_threshold
            if size_boundary or semantic_boundary:
                groups.append(current.strip())
                current = unit
            else:
                current = f"{current}\n{unit}"
        groups.append(current.strip())

        overlapped: list[str] = []
        for index, group in enumerate(groups):
            if index and self.chunk_overlap:
                prefix = groups[index - 1][-self.chunk_overlap :].lstrip()
                group = f"{prefix}\n{group}" if prefix else group
            overlapped.append(group)
        return [
            Document(page_content=group, metadata=dict(metadata))
            for group in overlapped
            if group
        ]

    def _units(self, text: str, metadata: JsonObject) -> list[str]:
        raw_units = [
            part.strip() for part in self._BOUNDARY.split(text) if part.strip()
        ]
        units: list[str] = []
        for raw in raw_units:
            if len(raw) <= self.chunk_size:
                units.append(raw)
                continue
            units.extend(
                document.page_content
                for document in self.recursive.split(raw, metadata)
                if document.page_content.strip()
            )
        return units


@dataclass(frozen=True)
class ChunkStrategySelector:
    default_strategy: ChunkStrategyName
    document_strategies: Mapping[str, ChunkStrategyName]
    recursive: RecursiveChunkStrategy
    semantic: SemanticChunkStrategy

    def select(
        self,
        requested: ChunkStrategyName,
        metadata: JsonObject,
    ) -> RecursiveChunkStrategy | SemanticChunkStrategy:
        resolved = requested
        if requested == "auto":
            document_type = str(
                metadata.get("parser")
                or metadata.get("file_type")
                or metadata.get("source_type")
                or "text"
            ).casefold()
            document_type = document_type.removeprefix(".")
            resolved = self.document_strategies.get(
                document_type, self.default_strategy
            )
            if resolved == "auto":
                resolved = "recursive"
        return self.semantic if resolved == "semantic" else self.recursive

    def split(
        self,
        text: str,
        metadata: JsonObject,
        requested: ChunkStrategyName,
    ) -> tuple[str, list[Document]]:
        strategy = self.select(requested, metadata)
        documents = strategy.split(text, metadata)
        for document in documents:
            document.metadata["chunk_strategy"] = strategy.name
        return strategy.name, documents


__all__ = [
    "ChunkStrategyName",
    "ChunkStrategySelector",
    "RecursiveChunkStrategy",
    "SemanticChunkStrategy",
]
