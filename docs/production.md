# SafeMealAgent production architecture

The repository now has five separately testable layers: deterministic unit tests,
LangGraph graph/checkpoint tests, RAG fusion tests, disposable Testcontainers
integration tests, and the reviewed JSONL Agent regression benchmark.

## Stateful Agent execution

Every Graph invocation uses `session_id` as its LangGraph `thread_id`. SQLite is
the durable local checkpointer and PostgreSQL is required by production validation
for shared HA state. `generate_recipe` is protected by a human approval
interrupt; `POST /api/v1/agent/resume` resumes the exact saved execution with an
approve/reject decision. In a multi-replica cluster, point the checkpointer and
BM25 files at a shared RWX volume or replace them with shared PostgreSQL/search
adapters before scaling. The manifests use a shared RWX volume for BM25/uploads and
expect `AGENT_CHECKPOINT_DATABASE_URL` in `safemeal-secrets` for PostgreSQL.

## Ingestion and retrieval

`POST /api/v1/upload/file/ingest-async` writes a tenant-scoped Redis job and returns
202. The independent worker runs parsing, scanned-PDF/image OCR, chunking, embeddings,
Milvus replacement, and SQLite FTS5 BM25 replacement. Search recalls vector and BM25
candidates, applies Reciprocal Rank Fusion, optional reranking, and document diversity.

## MCP and observability

The streamable HTTP MCP endpoint is mounted at `/mcp` and exposes
`food_safety_query`, `recipe_search`, and `nutrition_analysis`. The MCP client gateway
discovers and calls external streamable HTTP servers configured by the application.
The append-only JSONL trace remains the local audit record. Each completed trace is
also mirrored into OpenTelemetry spans and can be exported to an LLMOps webhook.

## Identity and isolation

Production enables OIDC verification of issuer, audience, signature, expiry, and the
configured tenant claim. Persistence identities are namespaced as `tenant:subject`;
knowledge documents and ingestion jobs carry the tenant id. Production must provision
`safemeal-secrets` with database, model, OIDC and OTLP values and must use managed HA
MySQL/Redis/Milvus/Neo4j rather than the development Compose instances.

## Verification

```bash
make test
RUN_TESTCONTAINERS=1 python -m pytest -m testcontainers
python -m safemeal.evaluation run --output evaluation_results/latest.json
kubectl kustomize deploy/k8s/base >/dev/null
docker compose config --quiet
```
