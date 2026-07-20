"""
Neo4j 投影的图加载和缓存辅助函数。
"""

import json
from pathlib import Path

from neo4j.graph import Graph, Node, Relationship

from SafeMealAgent.back.shared.types import JsonObject, to_json_object


def _convert_node(node: Node) -> JsonObject:
    data = dict(node.items())
    data["id"] = node.id
    data["labels"] = list(node.labels)
    return to_json_object(data)


def _convert_relationship(rel: Relationship) -> JsonObject:
    if rel.start_node is None or rel.end_node is None:
        raise ValueError("Neo4j relationship is missing an endpoint")
    payload = dict(rel.items())
    payload["source"] = rel.start_node.id
    payload["target"] = rel.end_node.id
    payload["type"] = rel.type
    return to_json_object(payload)


def convert_graph(graph: Graph) -> JsonObject:
    return {
        "nodes": [_convert_node(node) for node in graph.nodes],
        "relationships": [_convert_relationship(rel) for rel in graph.relationships],
    }


class GraphCache:
    """用于默认图形快照的简单文件缓存。"""

    def __init__(self, cache_path: Path) -> None:
        self.cache_path = cache_path
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> JsonObject | None:
        if not self.cache_path.is_file():
            return None
        with self.cache_path.open("r", encoding="utf-8") as fp:
            return json.load(fp)

    def save(self, graph: JsonObject) -> None:
        with self.cache_path.open("w", encoding="utf-8") as fp:
            json.dump(graph, fp, ensure_ascii=False)

    def invalidate(self) -> None:
        if self.cache_path.is_file():
            self.cache_path.unlink()
