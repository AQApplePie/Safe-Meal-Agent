# SafeMealAgent production architecture

The regression tests cover Workflow/Agent boundaries, allergy safety, streaming,
checkpoint recovery and execution budgets. The standalone benchmark and monitoring
subsystems have been removed.

## Stateful Agent execution

Every Graph invocation uses `session_id` as its LangGraph `thread_id`. SQLite is
the durable local checkpointer and PostgreSQL is required by production validation
for shared HA state. `generate_recipe` is protected by a human approval
interrupt; `POST /api/v1/chat/resume` resumes the exact saved execution with an
approve/reject decision. In a multi-replica cluster, point the checkpointer and
BM25 files at a shared RWX volume or replace them with shared PostgreSQL/search
adapters before scaling. The manifests use a shared RWX volume for BM25/uploads and
expect `AGENT_CHECKPOINT_DATABASE_URL` in `safemeal-secrets` for PostgreSQL.

## Ingestion and retrieval

`POST /api/v1/knowledge/files/async` writes a tenant-scoped Redis job and returns
202. The independent worker runs parsing, scanned-PDF/image OCR, chunking, embeddings,
Milvus replacement, and SQLite FTS5 BM25 replacement. Search recalls vector and BM25
candidates, applies Reciprocal Rank Fusion, optional reranking, and document diversity.

## Identity and isolation

The application supports local accounts with Argon2id password hashes, short-lived
signed access tokens and rotating refresh tokens. Refresh tokens are stored only as
hashes, and replay revokes the account's full token family. Alternatively, production
can enable OIDC verification of issuer, audience, signature, expiry and the configured
tenant claim. Persistence identities are namespaced as `tenant:subject`; knowledge
documents and ingestion jobs carry the tenant id. Production must provision
`safemeal-secrets` with database/model values and either `AUTH_JWT_SECRET` for local
identity or the OIDC settings. It must use managed HA MySQL/Redis/Milvus/Neo4j rather
than the development Compose instances.

## Verification

```bash
make test
kubectl kustomize deploy/k8s/base >/dev/null
docker compose config --quiet
```
