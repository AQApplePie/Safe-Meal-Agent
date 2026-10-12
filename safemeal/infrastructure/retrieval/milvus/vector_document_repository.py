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


# 方法说明：_load_collection_worker
# 作用：在独立执行单元中加载 Milvus 集合并报告结果。
# 入参：
#   host（str）：外部服务主机地址。
#   port（int）：外部服务端口。
#   collection_name（str）：向量集合名称。
#   timeout_seconds（float）：操作超时上限，单位秒。
#   result_queue（multiprocessing.Queue）：跨执行单元传递初始化结果的队列。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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


# 方法说明：load_collection_with_hard_timeout
# 作用：在硬超时边界内加载 Milvus 集合，避免启动无限等待。
# 入参：
#   host（str）：外部服务主机地址。
#   port（int）：外部服务端口。
#   collection_name（str）：向量集合名称。
#   timeout_seconds（float）：操作超时上限，单位秒。
# 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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


# 类说明（业务或基础设施实现类）：MilvusVectorDocumentRepository
# 作用：实现Milvus 向量文档仓储，封装该组件的业务处理与依赖协作。
class MilvusVectorDocumentRepository:
    # 字段说明：_REQUIRED_FIELDS
    # 作用：REQUIREDFIELDS，供该组件初始化及运行控制使用。
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

    # 方法说明：__init__
    # 作用：初始化Milvus 向量文档仓储，保存注入依赖并建立初始配置或运行状态。
    # 入参：
    #   collection_name（str）：向量集合名称；默认值为 'recipes'。
    #   host（str）：外部服务主机地址；默认值为 'localhost'。
    #   port（int）：外部服务端口；默认值为 19530。
    #   dimension（int）：嵌入向量的维度；默认值为 1536。
    #   index_type（str）：Milvus 向量索引类型；默认值为 'IVF_FLAT'。
    #   metric_type（str）：向量距离度量类型；默认值为 'IP'。
    #   load_timeout_seconds（float）：集合加载的超时上限，单位秒；默认值为 30.0。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
        # 实例属性说明：collection_name
        # 作用：向量集合名称。
        self.collection_name = collection_name
        # 实例属性说明：host
        # 作用：外部服务主机地址。
        self.host = host
        # 实例属性说明：port
        # 作用：外部服务端口。
        self.port = port
        # 实例属性说明：dimension
        # 作用：嵌入向量的维度。
        self.dimension = dimension
        # 实例属性说明：index_type
        # 作用：Milvus 向量索引类型。
        self.index_type = index_type
        # 实例属性说明：metric_type
        # 作用：向量距离度量类型。
        self.metric_type = metric_type
        # 实例属性说明：load_timeout_seconds
        # 作用：集合加载的超时上限，单位秒。
        self.load_timeout_seconds = load_timeout_seconds
        # 实例属性说明：connection_alias
        # 作用：当前 Milvus 连接的独立别名，避免不同实例互相覆盖连接。
        self.connection_alias = f"safemeal_{uuid4().hex}"
        # 实例属性说明：collection
        # 作用：当前向量集合对象。
        # 类型：Collection | None。
        # 初始值：None。
        self.collection: Collection | None = None
        # 实例属性说明：_connected
        # 作用：外部存储连接是否已经建立。
        # 初始值：False。
        self._connected = False
        # 实例属性说明：_closed
        # 作用：资源是否已关闭。
        # 初始值：False。
        self._closed = False
        # 实例属性说明：enforce_hard_load_timeout
        # 作用：是否对 Milvus 集合加载施加硬超时，超时后终止等待。
        # 初始值：True。
        self.enforce_hard_load_timeout = True

        self._initialize()

    # 方法说明：_initialize
    # 作用：初始化 Milvus 客户端、集合及其检索结构。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_load_if_populated
    # 作用：集合已有数据时执行加载，供后续检索使用。
    # 入参：
    #   collection（Collection）：当前向量集合对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_create_collection
    # 作用：按预期字段、向量维度及索引配置创建 Milvus 集合。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_ensure_vector_index
    # 作用：检查并为向量字段建立检索索引。
    # 入参：
    #   collection（Collection）：当前向量集合对象。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_validate_collection_schema
    # 作用：校验 Milvus 集合字段、类型与维度符合预期契约。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：_index_build_params
    # 作用：按索引类型生成 Milvus 建索引参数。
    # 入参：
    #   无显式入参。
    # 出参：JsonObject；JSON 字段映射。
    def _index_build_params(self) -> JsonObject:
        index_type = self.index_type.upper()
        if index_type.startswith("IVF_"):
            return {"nlist": 128}
        if index_type == "HNSW":
            return {"M": 16, "efConstruction": 200}
        return {}

    # 方法说明：_search_params
    # 作用：按向量索引类型生成检索时参数。
    # 入参：
    #   top_k（int）：检索返回的最大候选数。
    # 出参：JsonObject；JSON 字段映射。
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

    # 方法说明：_require_collection
    # 作用：确保 Milvus 集合存在且可访问。
    # 入参：
    #   无显式入参。
    # 出参：Collection；Milvus 集合。
    def _require_collection(self) -> Collection:
        if self.collection is None:
            raise RuntimeError("Milvus collection is not initialized")
        if self._closed:
            raise RuntimeError("Milvus vector store is closed")
        return self.collection

    # 方法说明：_as_varchar
    # 作用：将输入字段值转换为向量存储使用的字符字段内容。
    # 入参：
    #   value（MetadataScalar）：当前待转换或校验的值。
    # 出参：str；原值对应的字符字段值；原值为空时返回空字符串。
    @staticmethod
    def _as_varchar(value: MetadataScalar) -> str:
        return "" if value is None else str(value)

    # 方法说明：_validate_lengths
    # 作用：校验字符串字段长度，防止写入超过 SQL 列限制的数据。
    # 入参：
    #   ids（Sequence[str]）：待处理记录标识集合。
    #   embeddings（Sequence[Sequence[float]]）：与文本顺序对应的向量集合。
    #   documents（Sequence[str]）：待处理的文档或文档片段集合。
    #   metadatas（Sequence[JsonObject]）：文档、消息或证据的来源与辅助元数据。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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

    # 方法说明：add_documents
    # 作用：将文档片段及元数据加入检索存储。
    # 入参：
    #   ids（List[str]）：待处理记录标识集合。
    #   embeddings（List[List[float]]）：与文本顺序对应的向量集合。
    #   documents（List[str]）：待处理的文档或文档片段集合。
    #   metadatas（Optional[List[JsonObject]]）：文档、消息或证据的来源与辅助元数据；默认值为 None。
    # 出参：bool；对应存储更新或删除是否完成。
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

    # 方法说明：replace_document
    # 作用：用新片段替换同一文档的词法索引记录。
    # 入参：
    #   document_id（str）：文档标识。
    #   ids（List[str]）：待处理记录标识集合。
    #   embeddings（List[List[float]]）：与文本顺序对应的向量集合。
    #   documents（List[str]）：待处理的文档或文档片段集合。
    #   metadatas（List[JsonObject]）：文档、消息或证据的来源与辅助元数据。
    # 出参：bool；对应存储更新或删除是否完成。
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

    # 方法说明：search
    # 作用：通过Milvus 向量文档仓储按查询条件检索候选及其证据。
    # 入参：
    #   query_embedding（List[float]）：检索问题对应的向量。
    #   top_k（int）：检索返回的最大候选数；默认值为 10。
    #   filter_expr（Optional[str]）：当前检索使用的过滤条件或表达式；默认值为 None。
    # 出参：List[JsonObject]；JSON 字段映射的集合。
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

    # 方法说明：_in_expression
    # 作用：构造适配向量数据库语法的集合匹配表达式。
    # 入参：
    #   field（str）：当前待读取或校验字段名称。
    #   values（Sequence[str]）：当前待处理的值集合。
    # 出参：str；向量检索使用的集合匹配表达式文本。
    @staticmethod
    def _in_expression(field: str, values: Sequence[str]) -> str:
        serialized = ", ".join(
            json.dumps(str(value), ensure_ascii=False) for value in values
        )
        return f"{field} in [{serialized}]"

    # 方法说明：delete_documents
    # 作用：按文档标识删除检索片段及索引数据。
    # 入参：
    #   ids（List[str]）：待处理记录标识集合。
    # 出参：bool；对应存储更新或删除是否完成。
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

    # 方法说明：get_collection_stats
    # 作用：查询知识检索集合的记录与索引统计信息。
    # 入参：
    #   无显式入参。
    # 出参：JsonObject；JSON 字段映射。
    def get_collection_stats(self) -> JsonObject:

        return {
            "name": self.collection_name,
            "document_count": self._require_collection().num_entities,
            "dimension": self.dimension,
            "index_type": self.index_type,
            "metric_type": self.metric_type,
        }

    # 方法说明：clear_collection
    # 作用：清空当前知识检索集合中的记录。
    # 入参：
    #   无显式入参。
    # 出参：bool；对应存储更新或删除是否完成。
    def clear_collection(self) -> bool:

        self._require_collection().drop()
        self.collection = None
        self._create_collection()
        logger.info(
            "knowledge.milvus_collection.cleared collection={}", self.collection_name
        )
        return True

    # 方法说明：close
    # 作用：关闭当前组件拥有的客户端或连接，释放外部资源。
    # 入参：
    #   无显式入参。
    # 出参：None；无返回值，结果通过本方法的状态更新或外部操作体现。
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
