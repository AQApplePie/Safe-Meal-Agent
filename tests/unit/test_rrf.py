from safemeal.infrastructure.retrieval.hybrid import reciprocal_rank_fusion


def test_rrf_rewards_documents_present_in_both_rankings() -> None:
    vector = [
        {"id": "vector-only", "content": "x", "score": 0.99},
        {"id": "shared", "content": "宫保鸡丁含花生", "score": 0.8},
    ]
    lexical = [
        {"id": "shared", "content": "宫保鸡丁含花生", "score": 8.0},
        {"id": "lexical-only", "content": "y", "score": 7.0},
    ]

    fused = reciprocal_rank_fusion(vector, lexical, rank_constant=1)

    assert fused[0]["id"] == "shared"
    assert fused[0]["retrieval_channels"] == ["vector", "bm25"]
