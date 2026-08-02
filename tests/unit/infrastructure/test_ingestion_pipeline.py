from __future__ import annotations

from typing import Sequence

import pytest

from safemeal.application.use_cases.knowledge.chunking import (
    ChunkStrategySelector,
    RecursiveChunkStrategy,
    SemanticChunkStrategy,
)
from safemeal.infrastructure.ingestion.documents import (
    DocumentParseError,
    DocumentParserRegistry,
)


class _SemanticEmbedder:
    def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [1.0, 0.0] if "水果" in text or "苹果" in text else [0.0, 1.0]
            for text in texts
        ]

    def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]


def test_auto_chunking_selects_semantic_strategy_by_document_type() -> None:
    recursive = RecursiveChunkStrategy(chunk_size=200, chunk_overlap=0)
    selector = ChunkStrategySelector(
        default_strategy="recursive",
        document_strategies={"pypdf": "semantic"},
        recursive=recursive,
        semantic=SemanticChunkStrategy(
            embedder=_SemanticEmbedder(),
            recursive=recursive,
            chunk_size=200,
            chunk_overlap=0,
            breakpoint_threshold=0.5,
            max_segments=20,
        ),
    )

    name, documents = selector.split(
        "苹果是一种水果。香蕉也是水果。汽车使用发动机。道路用于交通。",
        {"parser": "pypdf"},
        "auto",
    )

    assert name == "semantic"
    assert len(documents) == 2


def test_local_text_and_markdown_parsers() -> None:
    registry = DocumentParserRegistry()
    assert registry.parse("note.txt", "正文".encode()).text == "正文"
    assert registry.parse("recipe.md", b"# Recipe").parser == "markdown"


def test_unsupported_document_type_is_rejected() -> None:
    with pytest.raises(DocumentParseError, match="TXT"):
        DocumentParserRegistry().parse("slides.pptx", b"data")
