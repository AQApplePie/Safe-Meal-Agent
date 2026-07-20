"""对 LightRAG 工作目录进行文件系统检查。"""

from pathlib import Path

from SafeMealAgent.back.shared.types import JsonObject


INDEX_FILES = (
    "graph_chunk_entity_relation.graphml",
    "kv_store_doc_status.json",
    "kv_store_full_docs.json",
    "kv_store_text_chunks.json",
    "vdb_chunks.json",
    "vdb_entities.json",
    "vdb_relationships.json",
)


def collect_index_stats(
    working_dir: str,
    *,
    initialized: bool,
) -> JsonObject:
    """返回 LightRAG 的存在性和大小信息，无需初始化 LightRAG。"""

    root = Path(working_dir)
    files: dict[str, JsonObject] = {}
    total_size = 0
    for file_name in INDEX_FILES:
        path = root / file_name
        size = path.stat().st_size if path.exists() else 0
        total_size += size
        files[file_name] = {
            "exists": path.exists(),
            "size_bytes": size,
            "size_mb": round(size / 1024 / 1024, 2),
        }
    return {
        "working_dir": working_dir,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "files": files,
        "initialized": initialized,
    }
