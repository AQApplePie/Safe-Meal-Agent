"""实现知识文档的分块策略。"""

from __future__ import annotations

from dataclasses import dataclass
from math import sqrt
import re
from typing import Mapping, Sequence

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from safemeal.modules.knowledge.ports.retrieval.document_embedder import (
    DocumentEmbedder,
)
from safemeal.shared.types import JsonObject


from safemeal.modules.knowledge.contracts.ingestion import ChunkStrategyName


# 方法说明：_cosine
# 作用：计算两个特征向量的余弦相似度，零向量按无相似度处理。
# 入参：
#   left（Sequence[float]）：参与匹配或相似度计算的两侧输入。
#   right（Sequence[float]）：参与匹配或相似度计算的两侧输入。
# 出参：float；两个输入特征的余弦相似度。
def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = sqrt(sum(value * value for value in left)) * sqrt(
        sum(value * value for value in right)
    )
    if denominator == 0:
        return 0.0
    return sum(a * b for a, b in zip(left, right)) / denominator


# 类说明（业务或基础设施实现类）：RecursiveChunkStrategy
# 作用：实现递归字符分块策略，封装该组件的业务处理与依赖协作。
class RecursiveChunkStrategy:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'recursive'。
    name = "recursive"

    # 方法说明：__init__
    # 作用：初始化递归字符分块策略，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   chunk_size（int）：文档分块的目标字符数。
    #   chunk_overlap（int）：相邻文档片段的重叠字符数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        # 实例属性说明：splitter
        # 作用：按字符长度、重叠长度与分隔符进行递归文档切分的组件。
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
            length_function=len,
        )

    # 方法说明：split
    # 作用：按递归或语义策略切分文本，保留每个片段的文档元数据。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    # 出参：list[Document]；带正文和来源元数据的文档片段的集合。
    def split(self, text: str, metadata: JsonObject) -> list[Document]:
        document = Document(page_content=text, metadata=dict(metadata))
        return self.splitter.split_documents([document]) or [document]


# 类说明（业务或基础设施实现类）：SemanticChunkStrategy
# 作用：实现基于句子语义边界的分块策略，封装该组件的业务处理与依赖协作。
class SemanticChunkStrategy:
    # 字段说明：name
    # 作用：当前对象或字段的名称。
    # 初始值：'semantic'。
    name = "semantic"
    # 字段说明：_BOUNDARY
    # 作用：BOUNDARY，供该组件初始化及运行控制使用。
    _BOUNDARY = re.compile(r"(?<=[。！？!?；;])|\n{2,}")

    # 方法说明：__init__
    # 作用：初始化基于句子语义边界的分块策略，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   embedder（DocumentEmbedder）：将文本转换成向量的嵌入组件。
    #   recursive（RecursiveChunkStrategy）：递归字符分块策略组件。
    #   chunk_size（int）：文档分块的目标字符数。
    #   chunk_overlap（int）：相邻文档片段的重叠字符数。
    #   breakpoint_threshold（float）：语义分块的边界相似度阈值。
    #   max_segments（int）：单次语义分块最多处理的基础句段数。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
    def __init__(
        self,
        *,
        embedder: DocumentEmbedder,
        recursive: RecursiveChunkStrategy,
        chunk_size: int,
        chunk_overlap: int,
        breakpoint_threshold: float,
        max_segments: int,
    ) -> None:
        # 实例属性说明：embedder
        # 作用：将文本转换成向量的嵌入组件。
        self.embedder = embedder
        # 实例属性说明：recursive
        # 作用：递归字符分块策略组件。
        self.recursive = recursive
        # 实例属性说明：chunk_size
        # 作用：文档分块的目标字符数。
        self.chunk_size = chunk_size
        # 实例属性说明：chunk_overlap
        # 作用：相邻文档片段的重叠字符数。
        self.chunk_overlap = chunk_overlap
        # 实例属性说明：breakpoint_threshold
        # 作用：语义分块的边界相似度阈值。
        self.breakpoint_threshold = breakpoint_threshold
        # 实例属性说明：max_segments
        # 作用：单次语义分块最多处理的基础句段数。
        self.max_segments = max_segments

    # 方法说明：split
    # 作用：按递归或语义策略切分文本，保留每个片段的文档元数据。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    # 出参：list[Document]；带正文和来源元数据的文档片段的集合。
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

    # 方法说明：_units
    # 作用：按语义分块规则将文本拆分成基础句段。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    # 出参：list[str]；用于语义分块的基础文本句段。
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


# 类说明（数据契约类）：ChunkStrategySelector
# 作用：描述文档分块策略选择器的结构、类型及可校验字段。
@dataclass(frozen=True)
class ChunkStrategySelector:
    # 字段说明：default_strategy
    # 作用：未显式指定时使用的文档切分策略。
    # 类型：ChunkStrategyName。
    # 补充取值说明（类型别名或枚举）：
    #   auto：自动选择的模式。
    #   recursive：递归切分。
    #   semantic：语义匹配或切分。
    default_strategy: ChunkStrategyName
    # 字段说明：document_strategies
    # 作用：按文档类型指定的切分策略，覆盖通用默认策略。
    # 类型：Mapping[str, ChunkStrategyName]。
    # 补充取值说明（类型别名或枚举）：
    #   auto：自动选择的模式。
    #   recursive：递归切分。
    #   semantic：语义匹配或切分。
    document_strategies: Mapping[str, ChunkStrategyName]
    # 字段说明：recursive
    # 作用：递归字符分块策略组件。
    # 类型：RecursiveChunkStrategy。
    recursive: RecursiveChunkStrategy
    # 字段说明：semantic
    # 作用：语义分块策略组件。
    # 类型：SemanticChunkStrategy。
    semantic: SemanticChunkStrategy

    # 方法说明：select
    # 作用：通过文档分块策略选择器筛选与当前任务相关的候选信息。
    # 入参：
    #   requested（ChunkStrategyName）：用户请求的数量、策略或选择。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    # 出参：RecursiveChunkStrategy |
    # SemanticChunkStrategy；递归字符分块策略或基于句子语义边界的分块策略。
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

    # 方法说明：split
    # 作用：按递归或语义策略切分文本，保留每个片段的文档元数据。
    # 入参：
    #   text（str）：待解析、检索、切分或渲染的文本。
    #   metadata（JsonObject）：文档、消息或证据的来源与辅助元数据。
    #   requested（ChunkStrategyName）：用户请求的数量、策略或选择。
    # 出参：tuple[str, list[Document]]；文本字符串、带正文和来源元数据的文档片段的集合组成的元组。
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
