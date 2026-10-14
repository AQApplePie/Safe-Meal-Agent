# 文档 1/9：SafeMeal 两个项目的当前技术栈

日期：2026-10-09。面向 Python 后端与 Agent 应用开发实习投递。依据当前源码、requirements.txt、pyproject.toml、environment.yml、web/package-lock.json、Docker Compose、部署配置与训练记录整理。本阶段不删除文件，不实施后续优化。

## 1. 当前关系与版本口径

目前两个项目仍在一个模块化单体中，共享 HTTP 应用、装配容器、业务契约、数据库与前端。下面按业务职责划分技术栈，不代表已经完成独立部署。

Python 依赖表记录 requirements.txt 的声明版本；其中范围依赖不等于已安装的精确版本。前端记录 package-lock.json 锁定版本。容器记录镜像标签，不等于真实部署或高可用验证。模型名为代码/配置与训练记录中的默认选型，不代表每次实际请求都使用该模型。

## 2. 传统后端：SafeMeal Recipe Platform

| 层次 | 当前技术 | 项目用途 |
|---|---|---|
| 语言 | Python；项目声明 >=3.11,<3.13；Conda/Docker 使用 3.12 | 服务端业务、数据库与后台任务 |
| Web | FastAPI 0.109.0、Starlette 0.35.1、Uvicorn 0.27.0 | REST API、路由、依赖注入与 ASGI 服务 |
| 契约与配置 | Pydantic 2.10.4、pydantic-settings 2.4.0 | 请求/响应校验、领域契约、环境配置 |
| 架构 | 模块化单体；application/contracts/ports；Composition Root | HTTP、业务与基础设施解耦 |
| 主存储 | MySQL 8.0 镜像、SQLAlchemy 2.0.25、PyMySQL 1.1.0 | 食谱、账号、点赞收藏、历史与 outbox |
| Schema | Alembic 1.13.1 | 版本化迁移；目前含 20261008_0012 发件箱迁移 |
| 查询 | SQL 索引、JOIN/聚合、有界 offset、历史 keyset cursor | 筛选、列表、个人行为、统计 |
| 缓存 | Redis 7 镜像、redis-py 5.0.1；有界进程内 L1 | cache-aside、空值缓存、TTL 抖动、故障回源 |
| 热点处理 | Python Lock 条带、进程内请求合并 | 同进程并发回源合并，不是跨实例互斥 |
| 榜单 | Redis ZSet/Hash、Lua、租约与快照原子发布 | 今日浏览用户数、当前点赞收藏统计；SQL 事实重建 |
| 行为事件 | Redis Streams、consumer group、XAUTOCLAIM；SQL outbox | 至少一次投递、持久去重、租约、退避重试、SQL 死信与恢复 |
| 认证 | PyJWT 2.8–<3、argon2-cffi 23.1–<26；可选 OIDC/JWKS | Access JWT、refresh 轮换/重放处理、密码哈希、租户身份 |
| 限流与日志 | Redis Lua 令牌桶、请求 ID、Loguru 0.7.2 | 请求治理、健康检查和日志定位 |
| 并发执行 | asyncio、线程池/run_in_threadpool、asyncio.to_thread | 异步请求中运行阻塞 SQL/Redis 调用与后台任务 |

对应目录：`modules/recipe`、`modules/identity`、`modules/interaction`，以及相关 HTTP router、persistence/cache/messaging 基础设施。

可用于项目介绍的核心栈：

> Python / FastAPI / Pydantic / SQLAlchemy / MySQL / Alembic / Redis / Redis Streams / JWT / Docker / pytest。

限制：真实 Redis 测试已有；当前新增后端 SQL 并发和执行计划测试主要用 SQLite，不能写成已经完成真实 MySQL 压测。传统后端入口目前仍受 Agent 装配与全量依赖影响，独立运行属于下一项优化。

## 3. Agent：SafeMeal Agent

| 层次 | 当前技术 | 项目用途 |
|---|---|---|
| 语言与接口 | Python 3.12、FastAPI、SSE、HTTPX 0.26.0 | Agent HTTP/SSE 接口、流式事件与模型/工具网络调用 |
| 状态编排 | LangGraph 0.2.60；自定义 Workflow、runtime 与 Tool Adapter | 外层工作流、内层规划/执行/观察/反思、结构化状态 |
| 模型接入 | LangChain OpenAI 0.2.14、langchain-core >=0.3.39,<0.4、OpenAI SDK >=1.58.1,<2 | OpenAI 兼容接口、结构化模型输出、供应商适配；SDK 名称不限定模型供应商 |
| 默认模型配置 | Qwen 系列；主模型配置默认 qwen3-max | 规划、反思、回答；部署时可更换兼容模型 |
| 契约 | Pydantic、结构化 RequestFrame/菜单/工具契约 | 数量、类别、实体、约束、工具参数和结果验证 |
| 安全机制 | 确定性领域规则、约束合并、结果复核 | 过敏/忌口和菜谱事实核对；非独立模型框架 |
| 多轮与记忆 | SQLAlchemy/MySQL 会话与用户记忆、结构化 active_menu | 长短期上下文、指代、菜单类别局部替换 |
| 本地 checkpoint | 自定义 SQLite LangGraph saver、msgpack/契约序列化 | 保存与恢复图执行状态 |
| 共享 checkpoint | langgraph-checkpoint-postgres >=2,<3、psycopg >=3.2,<4 | 可配置 PostgreSQL saver；生产配置要求不等于已验证 HA |
| 人工介入 | LangGraph interrupt 与 /chat/resume | 高影响工具的审批、拒绝和恢复；前端入口尚待补齐 |
| 文档召回 | Milvus 2.4.23 镜像、PyMilvus 2.4.15；SQLite FTS5/BM25 | 向量与关键词召回 |
| 检索融合 | 自研 RRF、文档多样性处理 | 合并召回候选 |
| Embedding/重排 | OpenAI 兼容 Embedding（默认 text-embedding-v4）；HTTP reranker（默认 qwen3-rerank） | 向量化与可选重排；实际启用依赖配置/凭据 |
| 图查询 | Neo4j 5 镜像、neo4j Python driver 5.27.0 | 食谱/食材关系与约束查询适配 |
| 文档摄取 | Redis 队列与独立 ingestion worker、LangChain text splitters | 异步解析、分块、向量和 BM25 索引更新 |
| 文档解析 | pypdf、PyMuPDF、Pillow、pytesseract | PDF/图片解析及可选 OCR；系统 Tesseract 仍需部署环境提供 |
| 预算 | 自定义 ModelBudget、供应商 usage、模型定价配置 | token/费用计量与执行预算；量化报告属于后续优化 |
| 请求理解 | 规则默认；可选本地模型 HTTP 网关与规则回退 | 请求语义识别，不直接替代工具执行/安全判定 |
| NLU 微调 | Qwen3-1.7B、MLX-LM、LoRA（rank 8、8 层） | Apple Silicon 本地训练与行为验收；不是默认 Web 服务依赖 |

NLU 训练记录包括 train/valid/test = 4800/600/600、实体划分与适配器配置。MLX-LM 使用单独本地训练环境，没有写入主 requirements.txt；训练产物与模型权重不应因“测试文件清理”被误删。文档中的训练结果尚需后续泛化评测验证。

Milvus 的 Compose 配套还有 etcd v3.5.5 与 MinIO RELEASE.2023-03-20T20-16-18Z，它们是向量存储的支撑组件，不应包装成两项独立的业务系统开发成果。

可用于项目介绍的核心栈：

> Python / FastAPI / LangGraph / Pydantic / OpenAI-compatible LLM / Tool Calling / SQL memory & checkpoint / Milvus + BM25 + RRF / Neo4j / SSE / Agent evaluation。

MLX/LoRA 是可选加分项；当前是单 Agent 架构，没有把多 Agent、Kafka、RabbitMQ、PyTorch 训练、RL 或 MCP 服务作为已实现能力列入。

## 4. 共享前端、交付与测试

| 类别 | 当前技术与证据 |
|---|---|
| 前端 | React 19.2.7、React DOM 19.2.7、JavaScript JSX、CSS；非 TypeScript 项目 |
| 前端构建 | Vite 6.4.3、React plugin 4.7.0；以上为 lockfile 版本 |
| UI/网络 | lucide-react 0.468.0、原生 fetch、ReadableStream SSE；原生 dialog、响应式 CSS |
| 运行环境 | Conda agent_env（Python 3.12）、Docker python:3.12-slim；前端未声明 Node engines |
| 部署配置 | Dockerfile、Docker Compose、Kubernetes/Kustomize 清单；不代表已经上线 |
| 后端测试 | pytest、pytest-asyncio、pytest-cov、testcontainers 依赖；SQLite 与隔离真实 Redis 用例 |
| 前端测试 | Node 原生 node:test；本地虚构 API fixture 与浏览器验收记录 |
| 质量检查 | Ruff、Mypy、架构依赖规则测试、Makefile 命令 |
| 项目管理 | Git、Markdown 文档、XML/JSON 测试与优化记录 |

最近保存的全量报告为 402 通过、1 跳过，其中传统后端专项 149 项；前端适配单元测试 6 项。此文档阶段没有重新跑测试，数字来自现有报告。根 README 缺失、CI 工作流未建立和历史架构文档过期等问题仍属于待优化事项。

## 5. 后续八项与文档约定

这里将“前四条”对应上一份实习评估中每个项目的前四项，按如下顺序实施：

| 文档编号 | 优化事项 | 主要验收 |
|---|---|---|
| 2/9 | 后端 1：独立轻量运行 | 清理审计与文件处理；独立入口/依赖/配置；API + MySQL + Redis；不初始化 Agent |
| 3/9 | 后端 2：真实 MySQL 联调 | 迁移、事务、并发、锁/失败处理与真实服务测试 |
| 4/9 | 后端 3：性能实验与 SQL 分析 | 固定数据与负载；执行计划；吞吐/延迟/错误率和优化对照 |
| 5/9 | 后端 4：运维闭环 | 最小指标、事件积压/死信观察、故障与恢复验收 |
| 6/9 | Agent 1：任务集与基线评测 | 固定任务、判定器、基线、重复运行与效果报告 |
| 7/9 | Agent 2：延迟/token/成本对照 | trace、调用次数、耗时、usage 完整性与优化对照 |
| 8/9 | Agent 3：人工审批与恢复展示 | 前端批准/拒绝、同一 checkpoint 恢复及跨刷新状态 |
| 9/9 | Agent 4：检索评测与消融 | 标注检索集、BM25/向量/融合/重排对比与归因 |

每项流程：实现 → 针对性测试与必要回归 → 审阅架构与变更 → 交付对应文档 → 等待用户确认下一项。完成前四项后端并通过测试，才进入 Agent 部分；没有自动跨阶段执行。

清理不额外生成第十份文档，清理清单、理由和验证记录并入后端第一项文档。

## 6. 清理边界

用户已授权清理无用和测试用文件；按后续逐步确认要求，本阶段尚未执行。下一阶段先核查用途、Git 状态、代码/文档引用与可再生性，再清理确认无用的缓存、构建输出、过时临时 fixture 和重复产物。

有效单元/集成/E2E/架构测试、必要的脱敏回归证据和演示数据不会一概视为无用文件。SQL 迁移、用户上传、运行数据库、模型权重、LoRA 产物和训练/冻结评测数据不因名称含 test 或位于本地目录就删除。存在归属不明或唯一有效证据的文件，先记录并保留；不通过清理掩盖失败测试。
