"""实现知识与菜谱检索基础设施适配。"""

from __future__ import annotations

import json
import multiprocessing
from queue import Empty
from time import perf_counter
from typing import List, Optional, Sequence
from uuid import uuid4

from loguru import logger
from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from safemeal.shared.types import JsonObject

MetadataScalar = str | int | float | bool | None


def _load_collection_worker(
    host: str,
    port: int,
    collection_name: str,
    timeout_seconds: float,
    result_queue: multiprocessing.Queue,
) -> None:

    alias = f"safemeal_load_{uuid4().hex}"
    try:
        connections.connect(
            alias=alias,
            host=host,
            port=port,
            timeout=timeout_seconds,
        )
        Collection(name=collection_name, using=alias).load(timeout=timeout_seconds)
        result_queue.put(None)
    except BaseException as exc:
        result_queue.put(f"{type(exc).__name__}: {exc}")
    finally:
        try:
            connections.disconnect(alias)
        except BaseException:
            pass


def load_collection_with_hard_timeout(
    *,
    host: str,
    port: int,
    collection_name: str,
    timeout_seconds: float,
) -> None:

    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue(maxsize=1)
    process = context.Process(
        target=_load_collection_worker,
        args=(host, port, collection_name, timeout_seconds, result_queue),
        daemon=True,
    )
    process.start()
    process.join(timeout_seconds)
    if process.is_alive():
        process.terminate()
        process.join(5)
        raise TimeoutError(
            f"Milvus collection load exceeded {timeout_seconds:.3f}s: {collection_name}"
        )
    try:
        error = result_queue.get_nowait()
    except Empty as exc:
        raise RuntimeError(
            f"Milvus load worker exited without a result (exit={process.exitcode})"
        ) from exc
    finally:
        result_queue.close()
    if error:
        raise RuntimeError(f"Milvus collection load failed: {error}")


class MilvusVectorDocumentRepository:

    _REQUIRED_FIELDS = {
        "id",
        "document_id",
        "tenant_id",
        "embedding",
        "content",
        "recipe_id",
        "name",
        "category",
        "difficulty",
    }

    def __init__(
        self,
        collection_name: str = "recipes",
        host: str = "localhost",
        port: int = 19530,
        dimension: int = 1536,
        index_type: str = "IVF_FLAT",
        metric_type: str = "IP",
        load_timeout_seconds: float = 30.0,
    ) -> None:
        self.collection_name = collection_name
        self.host = host
        self.port = port
        self.dimension = dimension
        self.index_type = index_type
        self.metric_type = metric_type
        self.load_timeout_seconds = load_timeout_seconds
        self.connection_alias = f"safemeal_{uuid4().hex}"
        self.collection: Collection | None = None
        self._connected = False
        self._closed = False
        self.enforce_hard_load_timeout = True

        self._initialize()

    def _initialize(self) -> None:

        started = perf_counter()
        logger.info(
            "knowledge.milvus_connect.start host={} port={} collection={}",
            self.host,
            self.port,
            self.collection_name,
        )
        try:
            connections.connect(
                alias=self.connection_alias,
                host=self.host,
                port=self.port,
            )
            self._connected = True

            if utility.has_collection(
                self.collection_name,
                using=self.connection_alias,
            ):
                self.collection = Collection(
                    name=self.collection_name,
                    using=self.connection_alias,
                )
                self._validate_collection_schema()
            else:
                self._create_collection()

            collection = self._require_collection()
            self._load_if_populated(collection)
            logger.info(
                "knowledge.milvus_connect.completed collection={} elapsed_ms={:.3f}",
                self.collection_name,
                (perf_counter() - started) * 1000,
            )
        except Exception:
            logger.exception(
                "knowledge.milvus_connect.failed host={} port={} collection={} "
                "elapsed_ms={:.3f}",
                self.host,
                self.port,
                self.collection_name,
                (perf_counter() - started) * 1000,
            )
            if self._connected:
                connections.disconnect(self.connection_alias)
                self._connected = False
            raise

    def _load_if_populated(self, collection: Collection) -> None:

        if collection.num_entities == 0:
            logger.info(
                "knowledge.milvus_load.skipped_empty collection={}",
                self.collection_name,
            )
            return
        self._ensure_vector_index(collection)
        if getattr(self, "enforce_hard_load_timeout", False):
            load_collection_with_hard_timeout(
                host=self.host,
                port=self.port,
                collection_name=self.collection_name,
                timeout_seconds=self.load_timeout_seconds,
            )
        else:
            collection.load(timeout=self.load_timeout_seconds)

    def _create_collection(self) -> None:

        fields = [
            FieldSchema(
                name="id",
                dtype=DataType.VARCHAR,
                is_primary=True,
                max_length=256,
            ),
            FieldSchema(
                name="document_id",
                dtype=DataType.VARCHAR,
                max_length=256,
            ),
            FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(
                name="embedding",
                dtype=DataType.FLOAT_VECTOR,
                dim=self.dimension,
            ),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="recipe_id", dtype=DataType.VARCHAR, max_length=256),
            FieldSchema(name="name", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="category", dtype=DataType.VARCHAR, max_length=128),
            FieldSchema(name="difficulty", dtype=DataType.VARCHAR, max_length=128),
        ]
        schema = CollectionSchema(
            fields=fields,
            description="Recipe knowledge base collection (schema v2)",
        )
        self.collection = Collection(
            name=self.collection_name,
            schema=schema,
            using=self.connection_alias,
        )

        logger.info(
            "knowledge.milvus_collection.created collection={}",
            self.collection_name,
        )

    def _ensure_vector_index(self, collection: Collection) -> None:

        if collection.indexes:
            return
        index_params: JsonObject = {
            "index_type": self.index_type,
            "metric_type": self.metric_type,
            "params": self._index_build_params(),
        }
        collection.create_index(
            field_name="embedding",
            index_params=index_params,
            timeout=self.load_timeout_seconds,
        )
        logger.info(
            "knowledge.milvus_collection.created collection={} index_type={}",
            self.collection_name,
            self.index_type,
        )

    def _validate_collection_schema(self) -> None:

        collection = self._require_collection()
        fields = {field.name: field for field in collection.schema.fields}
        missing = sorted(self._REQUIRED_FIELDS - fields.keys())
        if missing:
            if missing == ["document_id"] and collection.num_entities == 0:
                logger.warning(
                    "knowledge.milvus_schema.upgrade_empty_collection collection={}",
                    self.collection_name,
                )
                collection.drop()
                self.collection = None
                self._create_collection()
                return
            raise RuntimeError(
                "Milvus collection schema is incompatible; missing fields "
                f"{missing}. Recreate or migrate collection "
                f"{self.collection_name!r} before starting the service."
            )

        embedding_field = fields["embedding"]
        configured_dimension = getattr(embedding_field, "params", {}).get("dim")
        if (
            configured_dimension is not None
            and int(configured_dimension) != self.dimension
        ):
            raise RuntimeError(
                "Milvus embedding dimension mismatch: "
                f"collection={configured_dimension}, configured={self.dimension}"
            )

    def _index_build_params(self) -> JsonObject:
        index_type = self.index_type.upper()
        if index_type.startswith("IVF_"):
            return {"nlist": 128}
        if index_type == "HNSW":
            return {"M": 16, "efConstruction": 200}
        return {}

    def _search_params(self, top_k: int) -> JsonObject:
        index_type = self.index_type.upper()
        if index_type.startswith("IVF_"):
            return {"metric_type": self.metric_type, "params": {"nprobe": 10}}
        if index_type == "HNSW":
            return {
                "metric_type": self.metric_type,
                "params": {"ef": max(64, top_k)},
            }
        return {"metric_type": self.metric_type, "params": {}}

    def _require_collection(self) -> Collection:
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")
        if self._closed:
            raise RuntimeError("Milvus vector store is closed")
        return self.collection

    @staticmethod
    def _as_varchar(value: MetadataScalar) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def _validate_lengths(
        ids: Sequence[str],
        embeddings: Sequence[Sequence[float]],
        documents: Sequence[str],
        metadatas: Sequence[JsonObject],
    ) -> None:
        lengths = {len(ids), len(embeddings), len(documents), len(metadatas)}
        if len(lengths) != 1:
            raise ValueError(
                "ids, embeddings, documents and metadatas must have equal lengths"
            )
        if len(set(ids)) != len(ids):
            raise ValueError("document chunk ids must be unique within one insert")

    def add_documents(
        self,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: Optional[List[JsonObject]] = None,
    ) -> bool:

        if not ids:
            return True
        resolved_metadatas = metadatas or [{} for _ in ids]
        self._validate_lengths(ids, embeddings, documents, resolved_metadatas)
        if any(len(vector) != self.dimension for vector in embeddings):
            raise ValueError(
                f"all embeddings must have configured dimension {self.dimension}"
            )

        document_ids: list[str] = []
        for index, metadata in enumerate(resolved_metadatas):
            document_id = self._as_varchar(metadata.get("document_id")).strip()
            if not document_id:
                raise ValueError(f"metadata[{index}].document_id is required")
            document_ids.append(document_id)

        entities = [
            ids,
            document_ids,
            [
                self._as_varchar(meta.get("tenant_id") or "public")
                for meta in resolved_metadatas
            ],
            embeddings,
            documents,
            [self._as_varchar(meta.get("recipe_id")) for meta in resolved_metadatas],
            [self._as_varchar(meta.get("name")) for meta in resolved_metadatas],
            [self._as_varchar(meta.get("category")) for meta in resolved_metadatas],
            [self._as_varchar(meta.get("difficulty")) for meta in resolved_metadatas],
        ]
        collection = self._require_collection()
        collection.insert(entities, timeout=self.load_timeout_seconds)
        collection.flush(timeout=self.load_timeout_seconds)
        self._load_if_populated(collection)
        logger.info(
            "knowledge.milvus_insert.completed collection={} chunk_count={}",
            self.collection_name,
            len(ids),
        )
        return True

    def replace_document(
        self,
        document_id: str,
        ids: List[str],
        embeddings: List[List[float]],
        documents: List[str],
        metadatas: List[JsonObject],
    ) -> bool:

        normalized_id = str(document_id).strip()
        if not normalized_id:
            raise ValueError("document_id cannot be blank")
        if any(
            str(metadata.get("document_id", "")).strip() != normalized_id
            for metadata in metadatas
        ):
            raise ValueError("all replacement chunks must belong to document_id")

        self.delete_documents([normalized_id])
        return self.add_documents(ids, embeddings, documents, metadatas)

    def search(
        self,
        query_embedding: List[float],
        top_k: int = 10,
        filter_expr: Optional[str] = None,
    ) -> List[JsonObject]:

        if len(query_embedding) != self.dimension:
            raise ValueError(
                "query embedding dimension mismatch: "
                f"expected {self.dimension}, got {len(query_embedding)}"
            )
        if top_k <= 0:
            raise ValueError("top_k must be positive")

        started = perf_counter()
        logger.info(
            "knowledge.milvus_driver_search.start collection={} top_k={} "
            "filter_expr={} embedding_dimension={}",
            self.collection_name,
            top_k,
            filter_expr,
            len(query_embedding),
        )
        try:
            results = self._require_collection().search(
                data=[query_embedding],
                anns_field="embedding",
                param=self._search_params(top_k),
                limit=top_k,
                expr=filter_expr,
                output_fields=[
                    "id",
                    "document_id",
                    "tenant_id",
                    "content",
                    "recipe_id",
                    "name",
                    "category",
                    "difficulty",
                ],
            )
            formatted_results: List[JsonObject] = []
            for hits in results:
                for hit in hits:
                    document_id = hit.entity.get("document_id")
                    formatted_results.append(
                        {
                            "id": hit.entity.get("id"),
                            "content": hit.entity.get("content"),
                            "score": float(hit.score),
                            "metadata": {
                                "document_id": document_id,
                                "tenant_id": hit.entity.get("tenant_id"),
                                "recipe_id": hit.entity.get("recipe_id"),
                                "name": hit.entity.get("name"),
                                "category": hit.entity.get("category"),
                                "difficulty": hit.entity.get("difficulty"),
                            },
                        }
                    )
            logger.info(
                "knowledge.milvus_driver_search.completed collection={} "
                "result_count={} elapsed_ms={:.3f}",
                self.collection_name,
                len(formatted_results),
                (perf_counter() - started) * 1000,
            )
            return formatted_results
        except Exception:
            logger.exception(
                "knowledge.milvus_driver_search.failed collection={} elapsed_ms={:.3f}",
                self.collection_name,
                (perf_counter() - started) * 1000,
            )
            raise

    @staticmethod
    def _in_expression(field: str, values: Sequence[str]) -> str:
        serialized = ", ".join(
            json.dumps(str(value), ensure_ascii=False) for value in values
        )
        return f"{field} in [{serialized}]"

    def delete_documents(self, ids: List[str]) -> bool:

        document_ids = list(
            dict.fromkeys(str(value).strip() for value in ids if str(value).strip())
        )
        if not document_ids:
            return True
        expression = self._in_expression("document_id", document_ids)
        collection = self._require_collection()
        if collection.num_entities == 0:
            logger.info(
                "knowledge.milvus_delete.skipped_empty collection={} document_count={}",
                self.collection_name,
                len(document_ids),
            )
            return True
        collection.delete(expression, timeout=self.load_timeout_seconds)
        collection.flush(timeout=self.load_timeout_seconds)
        logger.info(
            "knowledge.milvus_delete.completed collection={} document_count={}",
            self.collection_name,
            len(document_ids),
        )
        return True

    def get_collection_stats(self) -> JsonObject:

        return {
            "name": self.collection_name,
            "document_count": self._require_collection().num_entities,
            "dimension": self.dimension,
            "index_type": self.index_type,
            "metric_type": self.metric_type,
        }

    def clear_collection(self) -> bool:

        self._require_collection().drop()
        self.collection = None
        self._create_collection()
        logger.info(
            "knowledge.milvus_collection.cleared collection={}", self.collection_name
        )
        return True

    def close(self) -> None:

        if self._closed:
            return
        if self._connected:
            connections.disconnect(self.connection_alias)
            self._connected = False
        self._closed = True
        self.collection = None
        logger.info(
            "knowledge.milvus_disconnect.completed alias={}",
            self.connection_alias,
        )
