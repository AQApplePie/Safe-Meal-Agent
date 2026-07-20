# SafeMeal Agent

SafeMeal Agent 是菜谱领域单 Agent 应用。运行主链使用 MySQL 结构化菜谱、Neo4j 食谱关系图、Milvus 语义检索和 LightRAG 跨文档关系检索；饮食与过敏硬约束由确定性领域代码执行，LLM 只负责语言理解、规划和结构化生成。

## 运行结构

```text
back/                 FastAPI、Agent、领域规则和基础设施适配器
web/                  React/Vite 用户界面
data/mysql/           MySQL 初始化数据
data/neo4j/           Neo4j 导入辅助数据
data/recipe.json      Neo4j 菜谱导入数据
Dockerfile            后端发布镜像
docker-compose.yml    MySQL、Redis、Neo4j、Milvus、LightRAG运行依赖
alembic.ini           数据库迁移入口
requirements.lock     后端可复现依赖锁
environment.yml       Python 3.11 Conda运行环境
```

## 配置

```bash
cp .env.example .env
```

至少配置数据库、模型、Embedding和可信身份网关参数。生产模式必须设置长度不少于32字符的`AUTH_GATEWAY_SECRET`，并由可信网关注入：

- `X-SafeMeal-Gateway-Secret`
- `X-SafeMeal-User-ID`
- `X-SafeMeal-Roles`

不要提交`.env`或真实密钥。

备用路由名已预配置为 `deepseekv4-pro`，实际 API 模型标识为
`deepseek-v4-pro`。由于 Agent 的结构化决策需要指定 `tool_choice`，该 Provider
显式关闭 DeepSeek Thinking 模式。默认
`DEEPSEEK_API_KEY=replace-with-real-deepseek-api-key` 只作为占位符，运行时会安全跳过；
替换为真实密钥后才会加入 Provider 路由。主模型发生连接、超时、限流或服务端错误时
才会切换备用模型；若主模型已经输出正文，则终止当前流而不切换，避免拼接两份答案。

## Docker启动

```bash
docker compose config --quiet
docker compose up -d --wait
```

Milvus 属于 retrieval profile：

```bash
docker compose --profile retrieval up -d etcd minio milvus
python -m back.evaluation prepare --target milvus
```

Apache Tika 属于 ingestion profile，`full` 镜像同时提供旧版 Office 解析和
Tesseract OCR：

```bash
docker compose --profile ingestion up -d tika
curl http://127.0.0.1:9998/version
```

本地后端使用 `TIKA_ENABLED=true` 和 `TIKA_URL=http://127.0.0.1:9998`；
Docker API 使用 `TIKA_URL_DOCKER=http://tika:9998`。已内置 TXT、Markdown、
JSON、CSV、HTML、PDF、DOCX、PPTX、XLSX 原生解析，并用 Tika 处理旧版 PPT、
RTF、ODF、EPUB以及原生解析失败或扫描 PDF 无文本的情况。

全新MySQL volume会执行Schema、70条Recipe seed和Alembic迁移。已有但没有`alembic_version`的数据库不能直接升级，必须先在仓库外备份并验证SHA-256：

```bash
make db-adopt backup_file=/absolute/path/backup.sql backup_sha256=<sha256>
make db-verify
```

不得用`alembic stamp head`掩盖旧库Schema差异，不得删除生产volume。

## 本地启动

```bash
conda env create -f environment.yml
conda activate safemeal_env
python -m pip install --require-hashes -r requirements.lock
cd web && npm ci && cd ..
make dev
```

后端默认监听`http://127.0.0.1:8000`，前端由Vite输出实际地址。也可分别运行：

```bash
make run-server
make run-web
```

## 健康检查

```bash
curl http://127.0.0.1:8000/livez
curl http://127.0.0.1:8000/readyz
curl http://127.0.0.1:8000/metrics
```

## 并发、成本与可观测性

设置 `REDIS_RATE_LIMIT_URL` 后，HTTP、模型和工具使用跨进程 Redis Token Bucket；
Agent 请求还会进入 Redis FIFO 并发队列。队列租约带过期时间，异常退出不会永久占用
容量；`AGENT_QUEUE_LEASE_SECONDS` 必须大于 `AGENT_TIMEOUT`。本地信号量继续作为单
进程第二层保护。

模型成本不在代码中写死，通过 `MODEL_PRICING_JSON` 按模型配置每百万 Token 的输入、
输出和缓存输入价格，并用 `MODEL_COST_CURRENCY` 指定币种。`LLM_MAX_OUTPUT_TOKENS` 限制
单次输出，`AGENT_MAX_MODEL_TOKENS` 和 `AGENT_MAX_COST` 限制一次 Agent 运行。启用金额
上限后，如果模型没有返回可信 Token usage 或没有对应价格，系统会停止后续付费调用，
避免在成本不可核验时继续消耗。价格应定期对照供应商官方计费页复核。

每次成功、降级和失败运行都会写入 `AGENT_TRACE_PATH`。文件权限为 `0600`，达到
`AGENT_TRACE_MAX_BYTES` 后轮转，保留数量由 `AGENT_TRACE_BACKUP_COUNT` 控制。Trace 包含
request/run/session 关联、Agent 节点、规划与反思理由、模型和工具调用、耗时、Token、
估算成本及错误。只有 internal 角色能查询：

```bash
curl 'http://127.0.0.1:8000/api/v1/observability/agent-traces?decisions_only=true&limit=20' \
  -H "X-SafeMeal-Gateway-Secret: $AUTH_GATEWAY_SECRET" \
  -H "X-SafeMeal-User-ID: operator" \
  -H "X-SafeMeal-Roles: internal"
```

`/metrics` 暴露 HTTP、首包、Agent 成功率与延迟、迭代数、模型/工具调用与延迟、
Token、成本、限流、队列深度/等待、熔断、反馈和 Trace 持久化指标。监控 profile
同时启动 Prometheus、Alertmanager、持久化通知接收器和预置 Agent Dashboard 的
Grafana：

```bash
make monitoring-up
open http://127.0.0.1:19090/alerts
open http://127.0.0.1:13000/d/safemeal-agent-overview
curl http://127.0.0.1:18090/alerts
```

Alertmanager 的 firing/resolved 通知先可靠追加到
`data/runtime/alerts.jsonl`。配置 `ALERT_NOTIFICATION_WEBHOOK_URL` 后会继续转发到企业
已有的 webhook 渠道；可用 `ALERT_NOTIFICATION_WEBHOOK_TOKEN` 加 Bearer 认证。

## 核心调用

```bash
curl -X POST http://127.0.0.1:8000/api/v1/chat/ \
  -H "X-SafeMeal-Gateway-Secret: $AUTH_GATEWAY_SECRET" \
  -H "X-SafeMeal-User-ID: demo-user" \
  -H "X-SafeMeal-Roles: user" \
  -H "Content-Type: application/json" \
  -d '{"message":"我花生过敏，请推荐两道安全菜谱。","user_id":"demo-user"}'
```

公开聊天 SSE（包含首包超时降级事件）：

```bash
curl -N -X POST http://127.0.0.1:8000/api/v1/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message":"推荐一道快手菜。","user_id":"demo-user"}'
```

文档上传入库可以显式选择 `auto`、`recursive` 或 `semantic` 分块。`auto` 会按
解析器类型使用 `KB_DOCUMENT_CHUNK_STRATEGIES_JSON` 中的策略：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/upload/file/ingest \
  -H "X-SafeMeal-Gateway-Secret: $AUTH_GATEWAY_SECRET" \
  -H "X-SafeMeal-User-ID: operator" \
  -H "X-SafeMeal-Roles: admin" \
  -F "file=@/absolute/path/document.pdf" \
  -F "chunk_strategy=auto"
```

单个来源支持 `local://`、`https://`、`s3://` 和 `feishu://` 手动同步：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sources/sync \
  -H "X-SafeMeal-Gateway-Secret: $AUTH_GATEWAY_SECRET" \
  -H "X-SafeMeal-User-ID: operator" \
  -H "X-SafeMeal-Roles: admin" \
  -H "Content-Type: application/json" \
  -d '{"source_uri":"local://handbook.pdf","chunk_strategy":"auto"}'
```

定时同步通过 JSON 配置，校验和未变化时跳过；失败任务会继续重试，源文件删除
时会同步删除对应 Milvus 分块：

```bash
SOURCE_SYNC_JOBS_JSON='[{"source_uri":"local://handbook.pdf","interval_seconds":300,"chunk_strategy":"auto"}]'
```

真实基础设施回归测试：

```bash
RUN_MODEL_FAILOVER_INTEGRATION=1 python -m pytest -q tests/integration/test_live_model_failover.py
RUN_RETRIEVAL_INTEGRATION=1 python -m pytest -q tests/integration/test_live_retrieval_pipeline.py
RUN_MULTI_ROUTE_INTEGRATION=1 python -m pytest -q tests/integration/test_live_retrieval_pipeline.py -k fusion
RUN_TIKA_INTEGRATION=1 python -m pytest -q tests/integration/test_live_ingestion_pipeline.py -k tika
RUN_INGESTION_INTEGRATION=1 python -m pytest -q tests/integration/test_live_ingestion_pipeline.py -k local_docx
RUN_REDIS_INTEGRATION=1 python -m pytest -q tests/integration/test_live_distributed_queue.py
RUN_OBSERVABILITY_INTEGRATION=1 python -m pytest -q tests/integration/test_live_observability_pipeline.py
```

Agent 运行时支持 Milvus、LightRAG、Neo4j 和结构化菜谱工具的并行选择；两路以上
检索结果会按加权 RRF 去重融合，单路失败时保留成功证据并标记降级来源。会话历史按
Token 预算保留最近消息并生成摘要/情景记忆，长期记忆按当前问题相关性筛选，过敏和
忌口始终优先。循环层限制迭代次数、工具总调用数和模型 Token，且会拦截相同工具参数
的重复调用。

冻结的 8 条评测语料已可通过 `python -m back.evaluation prepare --target both` 重建
Milvus 与 LightRAG 索引；LightRAG 插入会检查每个文档的最终 pipeline 状态，内部抽取
失败不会被报告为成功。旧 Neo4j 图的结构化食材完整性字段通过下面的幂等迁移补齐；
迁移会生成 `evaluation_results/neo4j-dietary-closure.json`，无法由受控源数据证明完整的
菜品仍保持 `unknown`：

```bash
make neo4j-dietary-sync
```

正负反馈都会持久化为每条 Agent 回答的当前反馈状态，负反馈另行幂等写入人工审核队列。
`GET /api/v1/feedback/stats?user_id=<id>` 返回正负数量、待审核数量和正反馈率。

完整验收使用冻结的 58 条评测集、LLM Judge 与 profile 门禁：

```bash
make eval-run
make eval-regression baseline=evaluation_results/baseline.json candidate=evaluation_results/latest.json
```

报告中的 `gates_passed` 才是 Top-1、Hit@5、faithfulness 等指标是否达标的唯一结论，
不能用静态数据集审计代替真实运行报告。
