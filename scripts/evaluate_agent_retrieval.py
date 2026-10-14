#!/usr/bin/env python3
"""Public synthetic corpus, real configured API vectors/reranking, exact local cosine.

Private-document and injection tests are separate, offline pytest cases.
--allow-provider-calls is required to build cache; replay does not contact APIs.
"""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
from safemeal.config.settings import settings  # noqa: E402
from safemeal.infrastructure.retrieval.milvus.document_embedder import (  # noqa: E402
    OpenAICompatibleDocumentEmbedder,
)
from safemeal.infrastructure.retrieval.milvus.document_reranker import (  # noqa: E402
    HttpDocumentReranker,
)
from safemeal.infrastructure.retrieval.sqlite_bm25 import SqliteBm25Repository  # noqa: E402
from safemeal.modules.knowledge.application.knowledge.document_knowledge_service import (  # noqa: E402
    DocumentKnowledgeService,
)
from safemeal.modules.knowledge.application.knowledge.chunking import _cosine  # noqa: E402


class CachedEmbedder:
    def __init__(self, vectors):
        self.vectors = vectors

    def embed_query(self, text):
        return self.vectors[text]

    def embed_documents(self, texts):
        return [self.vectors[text] for text in texts]


class CosineRepository:
    def __init__(self, docs, vectors):
        self.docs, self.vectors = docs, vectors

    def search(self, embedding, top_k, filter_expr):
        rows = [
            dict(
                id=d["id"] + "_0",
                document_id=d["id"],
                content=d["content"],
                metadata=dict(tenant_id="public", source=d["source"]),
                score=_cosine(embedding, self.vectors[d["content"]]),
            )
            for d in self.docs
        ]
        return sorted(rows, key=lambda row: row["score"], reverse=True)[:top_k]


class ReplayReranker:
    def __init__(self, cache, enabled):
        self.cache, self.enabled = cache, enabled

    async def rerank(self, query, documents, top_k):
        allowed = {d["id"]: d for d in documents}
        return [
            dict(allowed[d["id"]], rerank_score=d.get("rerank_score", 0))
            for d in self.cache[query]
            if d["id"] in allowed
        ][:top_k]


def metrics(ids, relevant, k):
    ids = list(dict.fromkeys(ids))[:k]
    return {
        "recall": len(set(ids) & set(relevant)) / len(relevant),
        "mrr": next((1 / (i + 1) for i, d in enumerate(ids) if d in relevant), 0),
    }


async def evaluate(args):
    path = ROOT / "tests/evaluation/datasets/retrieval_v1.json"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != path.with_suffix(".sha256").read_text().strip():
        raise ValueError("Corpus checksum mismatch")
    data = json.loads(path.read_text())
    # Explicit boundary: public, hand-authored benchmark only. No uploads/accounts/env text.
    if any(d["tenant_id"] != "public" for d in data["documents"]):
        raise ValueError("Private corpus forbidden")
    cp = Path(args.cache)
    cache = (
        json.loads(cp.read_text())
        if cp.exists()
        else dict(dataset_sha256=digest, vectors={}, rerankings={})
    )
    if cache["dataset_sha256"] != digest:
        raise ValueError("Cache checksum mismatch")
    if (
        cache["vectors"]
        and cache["embedding_model"].startswith("local-") != args.reference
    ):
        raise ValueError("Reference and provider caches cannot be mixed")
    calls = 0
    if args.reference and not cache["vectors"]:
        from sklearn.feature_extraction.text import TfidfVectorizer

        texts = [d["content"] for d in data["documents"]] + [
            q["query"] for q in data["queries"]
        ]
        model = TfidfVectorizer(analyzer="char", ngram_range=(1, 2))
        model.fit([d["content"] for d in data["documents"]])
        cache.update(
            vectors=dict(zip(texts, model.transform(texts).toarray().tolist())),
            embedding_model="local-char-tfidf-reference",
            reranker_model="local-token-coverage-reference",
        )
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    if not cache["vectors"]:
        if not args.allow_provider_calls:
            raise ValueError("Missing cache; opt in to public provider calls")
        texts = [d["content"] for d in data["documents"]] + [
            q["query"] for q in data["queries"]
        ]
        embedder = OpenAICompatibleDocumentEmbedder(
            model=settings.EMBEDDING_MODEL,
            api_key=settings.EMBEDDING_API_KEY,
            base_url=settings.EMBEDDING_BASE_URL,
            dimension=settings.EMBEDDING_DIMENSION,
        )
        vectors = await asyncio.to_thread(embedder.embed_documents, texts)
        cache.update(
            vectors=dict(zip(texts, vectors)),
            embedding_model=settings.EMBEDDING_MODEL,
            reranker_model=settings.RERANK_MODEL,
        )
        calls += 1
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps(cache, ensure_ascii=False, indent=2))
    baseline_source_sha256 = None
    service_class = DocumentKnowledgeService
    if args.baseline:
        import subprocess

        original = subprocess.check_output(
            [
                "git",
                "show",
                "HEAD:safemeal/modules/knowledge/application/knowledge/document_knowledge_service.py",
            ],
            cwd=ROOT,
            text=True,
        )
        baseline_source_sha256 = hashlib.sha256(original.encode()).hexdigest()
        namespace = {
            "__name__": "safemeal.modules.knowledge.application.knowledge._baseline",
            "__package__": "safemeal.modules.knowledge.application.knowledge",
        }
        exec(
            compile(original, "baseline_document_knowledge_service.py", "exec"),
            namespace,
        )
        service_class = namespace["DocumentKnowledgeService"]
    rows = []
    with tempfile.TemporaryDirectory(prefix="safemeal-rag-") as temp:
        lexical = SqliteBm25Repository(Path(temp) / "bm25.sqlite")
        for d in data["documents"]:
            lexical.replace_document(
                d["id"],
                [d["id"] + "_0"],
                [d["content"]],
                [dict(tenant_id="public", source=d["source"])],
            )
        vector = CosineRepository(data["documents"], cache["vectors"])
        provider = HttpDocumentReranker(
            enabled=True,
            provider=settings.RERANK_PROVIDER,
            base_url=settings.RERANK_BASE_URL,
            endpoint=settings.RERANK_ENDPOINT,
            model=settings.RERANK_MODEL,
            api_key=settings.RERANK_API_KEY,
            top_n=10,
            timeout=settings.RERANK_TIMEOUT,
        )
        for q in data["queries"]:
            for mode in ("bm25", "vector", "hybrid", "hybrid_rerank"):
                if mode == "bm25":
                    found = lexical.search(q["query"], 3, {"tenant_id": "public"})
                else:
                    service = service_class(
                        embedder=CachedEmbedder(cache["vectors"]),
                        vector_repository=vector,
                        lexical_repository=lexical,
                        reranker=ReplayReranker(cache["rerankings"], False),
                        chunk_size=500,
                        chunk_overlap=40,
                        top_k=3,
                        similarity_threshold=args.threshold,
                        rerank_max_candidates=10,
                        embedding_model=cache["embedding_model"],
                        reranker_model=cache["reranker_model"],
                        collection_name="isolated-exact-cosine",
                        hybrid_enabled=mode != "vector",
                    )
                    if mode == "hybrid_rerank":
                        if q["query"] not in cache["rerankings"]:
                            if not args.reference and (
                                not args.allow_provider_calls or not provider.enabled
                            ):
                                raise ValueError(
                                    "Rerank cache absent or provider unavailable"
                                )
                            candidates = await service.search(q["query"], top_k=10)
                            if args.reference:
                                from safemeal.infrastructure.retrieval.sqlite_bm25 import (
                                    _tokens,
                                )

                                terms = set(_tokens(q["query"]))
                                ranked = sorted(
                                    [
                                        dict(
                                            r,
                                            rerank_score=len(
                                                terms & set(_tokens(r["content"]))
                                            )
                                            / max(1, len(terms)),
                                        )
                                        for r in candidates
                                    ],
                                    key=lambda r: r["rerank_score"],
                                    reverse=True,
                                )
                            else:
                                ranked = await provider.rerank(
                                    q["query"], candidates, 10
                                )
                            if candidates and not any(
                                "rerank_score" in r for r in ranked
                            ):
                                raise ValueError(
                                    "Silent rerank fallback is not a live result"
                                )
                            cache["rerankings"][q["query"]] = ranked
                            calls += int(bool(candidates) and not args.reference)
                            cp.write_text(
                                json.dumps(cache, ensure_ascii=False, indent=2)
                            )
                        service.reranker = ReplayReranker(cache["rerankings"], True)
                    found = await service.search(q["query"], top_k=3)
                ids = [d["document_id"] for d in found]
                rows.append(
                    dict(
                        case_id=q["id"],
                        split=q["split"],
                        mode=mode,
                        query=q["query"],
                        relevant=q["relevant_documents"],
                        retrieved=ids,
                        chunk_ids=[d["id"] for d in found],
                        metrics_at_1=metrics(ids, q["relevant_documents"], 1),
                        metrics_at_3=metrics(ids, q["relevant_documents"], 3),
                    )
                )
    summaries = {}
    for split in ("dev", "test"):
        for mode in ("bm25", "vector", "hybrid", "hybrid_rerank"):
            group = [r for r in rows if r["split"] == split and r["mode"] == mode]
            summaries[split + "/" + mode] = {
                f"{m}@{k}": sum(r[f"metrics_at_{k}"][m] for r in group) / len(group)
                for m in ("recall", "mrr")
                for k in (1, 3)
            }
    report = dict(
        dataset_sha256=digest,
        cache_sha256=hashlib.sha256(cp.read_bytes()).hexdigest(),
        embedding_model=cache["embedding_model"],
        reranker_model=cache["reranker_model"],
        vector_storage="local exact cosine, NOT Milvus ANN",
        reference_only=args.reference,
        baseline_service_from_git_head=args.baseline,
        baseline_source_sha256=baseline_source_sha256,
        threshold=args.threshold,
        provider_requests_this_run=calls,
        summaries=summaries,
        rows=rows,
        failures=[r for r in rows if r["metrics_at_3"]["recall"] < 1],
    )
    Path(args.output).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        json.dumps(
            {k: v for k, v in report.items() if k not in {"rows", "failures"}},
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--reference", action="store_true")
    p.add_argument("--baseline", action="store_true")
    p.add_argument("--allow-provider-calls", action="store_true")
    p.add_argument("--cache", default="evaluation_results/agent_retrieval_cache.json")
    p.add_argument(
        "--output", default="evaluation_results/agent_retrieval_ablation.json"
    )
    p.add_argument("--threshold", type=float, default=0.7)
    asyncio.run(evaluate(p.parse_args()))
