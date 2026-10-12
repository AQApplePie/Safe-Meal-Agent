# SafeMealAgent production architecture

The regression tests cover Workflow/Agent boundaries, allergy safety, streaming,
checkpoint recovery and execution budgets. The standalone benchmark and monitoring
subsystems have been removed.

## Stateful Agent execution

Every Graph invocation uses `session_id` as its LangGraph `thread_id`. SQLite is
the durable local checkpointer and PostgreSQL is required by production validation
for shared HA state. `generate_recipe` is protected by a human approval
interrupt; `POST /api/v1/chat/resume` resumes the exact saved execution with an
approve/reject decision bound to `message_id` and `approval_id`. SQL atomically claims the approval and stores its decision before graph execution; the reviewed response replaces the pending message. Interrupted claims are blocked from replay until their outcome has been checked. See [approval verification](optimization/07_agent_approval_resume.md). In a multi-replica cluster, point the checkpointer and
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

Embedding 与 rerank 必须配置各自适用的服务和凭据。默认 `text-embedding-v4` 使用 DashScope 兼容地址；缺失凭据只允许从同主机 LLM 服务继承，不能把 DeepSeek 凭据自动发送到 DashScope。显式 EMBEDDING/RERANK 配置需要运维自行确认匹配。`EMBEDDING_API_KEY` 缺失时嵌入客户端拒绝启动，不退回读取全局聊天凭据。生产效果需按 [检索消融报告](optimization/08_agent_retrieval_quality_ablation.md) 的 opt-in 命令验证；本地 TF-IDF 结果不代表生产向量模型或 Milvus 效果。
