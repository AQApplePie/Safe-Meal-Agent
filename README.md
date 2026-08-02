# SafeMeal Agent

SafeMeal Agent 是一个面向求职展示的单机食谱 Agent 后端。项目保留能体现 Agent 工程能力的主链路，删除了面向大型线上系统的治理平台和重复数据源。

## 核心链路

1. FastAPI 接收聊天请求并加载会话历史。
2. 上下文构建器组合三层记忆：当前窗口、持久化情景摘要、长期用户画像。
3. Planner 在结构化菜谱、Milvus 文档检索和 Neo4j 领域工具之间选择。
4. Milvus 扩大候选召回，经 Rerank 后按 `document_id` 轮询，避免同一文档片段挤占结果。
5. Neo4j 只执行参数化的饮食约束与食谱推荐查询，不开放任意 Cypher。
6. 普通代码执行过敏/忌口硬过滤，LLM 负责规划和表达。
7. 运行过程保存稳定的 Agent Trace JSONL；离线评测保留确定性指标和 LLM Judge。

运行依赖只有 MySQL、Redis、Neo4j、Milvus（以及 Milvus 自带的 etcd、MinIO）。Redis 仅用于 HTTP Token Bucket；进程内并发由 `asyncio.Semaphore` 控制。

## 快速开始

```bash
conda activate agent_env
cp .env.example .env
# 在 .env 中填写 LLM_API_KEY
docker compose up -d --wait
```

Docker API 默认位于 `http://localhost:8000`，Swagger 位于 `http://localhost:8000/docs`。示例 API Key 为 `safemeal-local-api-key`，调用时放在 `X-API-Key`；可在 `.env` 中修改。若后端在宿主机运行：

```bash
python -m uvicorn safemeal.main:application --reload
```

首次准备检索与图谱数据：

```bash
python -m safemeal.evaluation prepare --target milvus
python -m safemeal.infrastructure.retrieval.neo4j.dietary_migration
```

本地上传仅支持 `.txt`、`.md` 和 `.pdf`。

## 测试与评测

```bash
PYTHONPATH=. python -m pytest -q
python -m safemeal.evaluation run --output evaluation_results/latest.json
```

外部服务测试默认跳过，按测试文件提示设置 `RUN_*_INTEGRATION=1` 后启用。评测默认使用 LLM Judge；仅调试时可加 `--no-judge`。付费 API 测试会消耗模型、Embedding 和 Rerank 配额。

## 目录

```text
safemeal/application/       Agent、记忆、聊天、评测用例
safemeal/domain/            食谱与饮食安全规则
safemeal/infrastructure/    MySQL、Milvus、Neo4j、Redis、LLM 适配器
safemeal/interfaces/http/   FastAPI 路由与中间件
data/evaluation/            冻结评测集和评测配置
tests/                      单元、接口、架构和显式集成测试
```

架构取舍和面试讲解见 [docs/architecture-cn.md](docs/architecture-cn.md)。
