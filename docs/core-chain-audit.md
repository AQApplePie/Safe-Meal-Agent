# 核心链路代码审阅

本次审阅以两个业务入口为准：食谱助手聊天、文件上传与知识入库。身份认证、限流、
数据库迁移、健康检查和后台入库 Worker 作为后端运行保障纳入保留范围。

## 生产链路

聊天链路为 `auth → chat router → ChatTurnService → Workflow → Agent → tools →
RecipeService/知识检索 → 饮食安全复核 → 持久化/流式响应`。

文件链路为 `auth → knowledge router → FileUploadService → 同步入库服务或 Redis
队列 → ingestion worker → 解析/OCR/分块 → Milvus + BM25`。

身份、聊天、记忆、食谱、饮食安全、Milvus/BM25、可选 Neo4j、checkpoint、同步与
异步文件入库、健康检查及限流代码均能从上述生产入口或运维入口到达。

## 已删除

- MCP Server 及三个对外 MCP 工具；
- 外部 MCP Client、`external_mcp_call` Agent 工具和相关审批特例；
- MCP 配置、依赖、端口契约、认证代码、测试和文档；
- 没有调用方的旧聊天异常、旧上下文约束抽取函数、旧饮食档案 DTO 和日志包装函数。

## 不在在线请求链路，但应保留

- `infrastructure/persistence/migrations/versions/`：部署升级数据库所需；
- `infrastructure/retrieval/neo4j/dietary_migration.py` 与 `importers/`：由
  `make neo4j-sync` 执行，为启用 Neo4j 的饮食安全查询准备数据；
- `infrastructure/ingestion/worker.py`：异步文件入库的独立进程入口；
- OIDC：本地账号系统的生产替代认证方式；
- `/health`、`/livez`、`/readyz` 和 Redis 限流：部署与高并发保护能力。

## 纯开发辅助文件

- `safemeal/print_project_tree.py` 只生成目录树；
- `SafeMealAgent.txt` 是它生成的项目结构快照。

这两个文件不参与任何生产或测试链路，可以删除，但它们不增加运行时耦合，也不会被
打包后的应用调用，因此本次只标记，不替用户删除项目说明资产。
