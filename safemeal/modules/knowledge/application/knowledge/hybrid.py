"""融合向量检索与关键词检索的排序结果。"""

from safemeal.shared.types import JsonObject


# 方法说明：reciprocal_rank_fusion
# 作用：按各检索通道的排名累加 RRF 分数并合并重复片段。
# 入参：
#   vector_results（list[JsonObject]）：向量通道召回的候选片段。
#   lexical_results（list[JsonObject]）：词法通道返回的候选片段。
#   rank_constant（int）：RRF 排名融合的平滑常数；默认值为 60。
# 出参：list[JsonObject]；JSON 字段映射的集合。
def reciprocal_rank_fusion(
    vector_results: list[JsonObject],
    lexical_results: list[JsonObject],
    *,
    rank_constant: int = 60,
) -> list[JsonObject]:

    if rank_constant < 1:
        raise ValueError("rank_constant must be positive")
    fused: dict[str, JsonObject] = {}
    scores: dict[str, float] = {}
    channels: dict[str, list[str]] = {}
    for channel, ranking in (("vector", vector_results), ("bm25", lexical_results)):
        seen: set[str] = set()
        for rank, item in enumerate(ranking, start=1):
            key = str(
                item.get("id")
                or item.get("chunk_id")
                or item.get("document_id")
                or f"{channel}-{rank}"
            )
            if key in seen:
                continue
            seen.add(key)
            fused.setdefault(key, dict(item))
            scores[key] = scores.get(key, 0.0) + 1.0 / (rank_constant + rank)
            channels.setdefault(key, []).append(channel)
    output: list[JsonObject] = []
    for key in sorted(scores, key=lambda item: scores[item], reverse=True):
        result = fused[key]
        result["rrf_score"] = scores[key]
        result["retrieval_channels"] = channels[key]
        output.append(result)
    return output


__all__ = ["reciprocal_rank_fusion"]
