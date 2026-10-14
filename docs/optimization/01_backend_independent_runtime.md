# 文档 2/9：传统后端第一项——独立轻量运行与文件清理

日期：2026-10-09。对应上一份评估的后端第一条。本项已完成实现、测试与架构审阅；下一项需用户确认后开始。本报告与技术栈文档属于约定的九份报告，根 README 仅提供项目入口导航。

## 1. 本项结果

SafeMeal Recipe Platform 现在可以仅用 API + MySQL + Redis 启动，提供食谱列表/详情、点赞收藏、浏览历史、榜单、账号与个人行为接口。独立环境没有安装 LangGraph、LangChain、OpenAI SDK、PyMilvus 或 Neo4j driver，不要求模型密钥，也不初始化 Agent checkpoint。

已实际构建 Docker 镜像，在全新隔离 MySQL/Redis 数据卷完成种子导入、迁移及 HTTP 验收。不是仅修改配置后推断能启动。Agent 仍通过原入口运行，两者复用相同业务实现。

## 2. 实现与文件定位

| 文件 | 作用 |
|---|---|
| `safemeal/platform_main.py` | 独立 ASGI 入口，读取 `.env.platform` 或 `SAFEMEAL_ENV_FILE` |
| `safemeal/bootstrap/composition/platform_application.py` | 应用工厂、lifespan、数据库/Redis 就绪探测 |
| `safemeal/bootstrap/composition/platform_container.py` | SQL、缓存、身份、交互与后台 worker 组合根 |
| `safemeal/bootstrap/composition/application_container.py` | Agent 容器继承共享组合根，继续装配模型、图、知识和 checkpoint |
| `safemeal/config/platform.py` | 共享基础配置与生产安全校验；Agent Settings 继承它 |
| `safemeal/interfaces/__init__.py` | 按入口选择公共路由与 Agent 路由；公共导入不再触发全部路由 |
| `safemeal/interfaces/http/platform_dependencies.py` | 公共服务依赖；旧依赖模块重导出同一函数，保留测试覆盖/override 行为 |
| `safemeal/interfaces/http/application.py` | 两个入口共用 CORS、请求治理与异常状态码映射 |
| `requirements-platform.txt` | 16 项直接运行依赖，与全量清单的公共版本保持一致 |
| `Dockerfile.platform` | 轻量镜像，以 UID 10001 非 root 运行 |
| `docker-compose.platform.yml` | 三个持续运行服务及一个一次性迁移任务，独立数据卷与端口 |
| `.env.platform.example` | 无模型配置的本地后端示例，已加入 Git 忽略例外 |
| `scripts/platform_smoke.py` | 可重复的真实 HTTP 主链路验收脚本 |
| `tests/backend/test_platform_runtime.py` | 10 项新增运行隔离、就绪、生产校验和资源关闭测试 |

配置包取消导入时隐式实例化 Agent 配置；迁移环境只读取基础 SQL 配置。健康检查/限流公共装配不再提前加载 Agent 配置。

`Settings` 保留 Agent 的 `.env` 读取、模型校验和生产共享 checkpoint 要求。平台生产配置保留 MySQL、禁用 DEBUG、CORS、JWT/OIDC 安全校验。独立入口不读取 Agent `.env`；无明确配置时也不会悄悄生成本地业务数据库。

## 3. 清理记录

先检查 Git 状态、内容、引用与可再生性，再删除。最初清理 95 个路径、376,550,221 bytes，约 359.1 MiB；质量检查会重新生成部分缓存，收尾再清理。逐项路径、字节数、目录快照哈希见 `evaluation_results/platform_cleanup.json`。

| 处理 | 理由 |
|---|---|
| 删除 `.mypy_cache`、`.pytest_cache`、`.ruff_cache` | 可由质量检查再生，主要空间占用来源 |
| 删除 `web/dist` | Vite 构建输出；源代码及依赖锁保留 |
| 删除源码与测试中的 `__pycache__` | Python 字节码缓存，不承担业务或测试职责 |
| 删除 `Safe-Meal-Agent.txt`、`safemeal/safemeal.txt` | 无有效运行引用的过期目录树，包含已删除/已移动路径；仅历史 Git 状态文本提及 |
| 保留所有有效测试、`web/tests/fixture_server.py` | 仍有回归与浏览器验收用途 |
| 保留 `evaluation_results` 既有有效报告与截图 | 包含唯一验收/失败归因证据，不属于无用临时文件 |
| 保留上传、运行数据库、种子、迁移、训练数据、权重及 LoRA 产物 | 属于数据或必要交付，未因名称含 test 而删除 |

没有重置预先存在的 Git 修改，没有操作原 Agent 数据库/数据卷。架构文档中的 Interaction 未实现描述已补充当前状态，历史评估和技术栈文档仍保留生成时口径。

## 4. 启动与演示

### 4.1 Docker：完整本地演示

从仓库根目录执行，需 Docker Desktop 已运行：

```sh
docker compose --env-file .env.platform.example -f docker-compose.platform.yml up --build -d --wait
```

访问 `http://localhost:8100/docs`，就绪检查 `http://localhost:8100/readyz`。

默认端口：API 8100、MySQL 23306、Redis 26379；后两者仅绑定本机。与原 Agent Compose 默认端口分开。项目名为 `safemeal-platform`，使用自己的 MySQL/Redis 数据卷。镜像为 `safemeal-platform:local`。

启动顺序：MySQL 首次创建数据卷时执行 `init_mysql.sql` 与 `insert_sample_data.sql` → 迁移任务 `alembic upgrade head` 成功退出 → API 启动后台榜单/行为 worker。Redis 配置为 AOF。MySQL 初始化 SQL 中的数据库名为 `recipe_db`，本 Compose 也使用该固定名称。

普通停止保留数据：

```sh
docker compose --env-file .env.platform.example -f docker-compose.platform.yml down
```

重复启动不会重新导入种子；迁移升到现有 head 后正常退出。不能通过反复运行初始化 SQL 给已有数据库覆盖数据。

### 4.2 本地 Python：轻量依赖

```sh
python3.12 -m venv .venv-platform
.venv-platform/bin/python -m pip install -r requirements-platform.txt
cp .env.platform.example .env.platform
```

如果希望 MySQL/Redis 在 Docker、API 在本机：

```sh
docker compose --env-file .env.platform -f docker-compose.platform.yml up -d --wait mysql redis
SAFEMEAL_ENV_FILE=.env.platform .venv-platform/bin/alembic upgrade head
.venv-platform/bin/uvicorn safemeal.platform_main:app --host 127.0.0.1 --port 8100
```

环境变量优先于配置文件；可通过 `SAFEMEAL_ENV_FILE` 指定另一份平台配置。`.env.platform` 为本地文件，不应提交。示例是开发配置，生产应设置 `APP_ENV=production` 并通过前述安全校验。

### 4.3 HTTP smoke

在上述 API 运行后：

```sh
.venv-platform/bin/python scripts/platform_smoke.py --base-url http://127.0.0.1:8100 --report /tmp/platform-smoke.json
```

脚本会创建随机命名的演示账号，执行读取、重复点赞、收藏、历史、榜单、refresh/logout/login，并取消测试点赞/收藏。账号与浏览历史留在演示库；仅对演示或专用测试环境运行，避免把它当成无写入的生产健康检查。

`/livez` 只表示进程存活；`/readyz` 检查平台必需表及已配置 Redis 连接，缺表/依赖失联返回 503。它不探测模型、Milvus 或 Neo4j，也不把 Agent 会话表作为平台就绪条件。

## 5. 测试结果与证据

| 检查 | 实际结果 |
|---|---|
| 最终全量 pytest | 412 passed、1 skipped；新增 10 项包含在总数中 |
| Ruff | `safemeal`、`tests` 与新 smoke 脚本通过；本项修改的 Python 文件格式化 |
| Mypy | 301 个源码文件通过 |
| 隔离轻量 venv | 仅安装 `requirements-platform.txt`，36 个发行包；SQLite HTTP 主链路通过，导入拦截器禁止 Agent/模型 SDK |
| Docker Compose | 构建与启动成功；API/MySQL/Redis healthy，迁移任务 exit 0 |
| 全新 MySQL 迁移 | 从初始版本升至 `20261008_0012`，70 条种子食谱 |
| 真实 HTTP | 21 项检查通过，包含未登录写入 401 与幂等重复点赞 |
| 容器运行边界 | UID 10001；未安装五类 Agent SDK；Agent 导入列表为空；无 checkpoint 初始化 |

实测 Docker daemon 29.3.0、MySQL 8.0.46、Redis 7.4.11。本项验证项目为 `safemeal-platform-verify-20261009`，验证端口 18100/23316/26389；这些不是默认使用端口。验收后已移除仅本次创建的验证容器、网络与数据卷，保留结果报告；Docker Desktop 保持运行。最初 Docker 未运行，已启动本机 Docker Desktop 后完成验收。

证据：

- `evaluation_results/platform_final_pytest.xml`：最终全量测试。
- `evaluation_results/platform_minimal_environment.json`：轻量 venv 安装清单与 smoke 结果。
- `evaluation_results/platform_docker_smoke.json`：真实 HTTP 21 项。
- `evaluation_results/platform_docker_runtime.json`：MySQL/Redis 版本、迁移、容器隔离与种子数据证据。
- `evaluation_results/platform_cleanup.json`：文件处理审计。

现有一项真实模型 E2E（`test_register_login_and_three_memory_aware_turns`）需显式设置 `RUN_DEEPSEEK_E2E=1` 并指定 live API，本次按原规则跳过，未计入通过数。SQLite smoke 通过 ORM metadata 创建临时测试结构；已有历史迁移使用 MySQL DDL，本项没有为了 SQLite 改写历史迁移。真正的迁移启动验收在 Docker MySQL 执行。初次新增测试暴露了 fixture 食谱缺少必要步骤/食材、smoke 对收藏响应字段的错误假设，修正后全量回归通过。

## 6. 架构审阅

| 边界 | 结论 |
|---|---|
| HTTP → application/contracts | 公共路由只调用业务服务，不加入 SQL/Redis 或 Agent 决策逻辑 |
| Composition Root → infrastructure | 平台装配位于 bootstrap；薄入口不直接使用基础设施 |
| Agent 与公共后端 | Agent 容器继承平台装配，不复制另一套仓储/身份/交互逻辑 |
| 配置隔离 | 平台可独立校验，Agent 在共享校验后继续自身校验 |
| 请求兼容 | 公共 URL、认证身份与异常映射保持兼容；旧 dependency override 仍引用相同函数 |
| 生命周期 | 审阅补强：任一 worker 关闭失败仍关闭其他 worker/SQL/Redis；Agent 摄取队列关闭失败仍释放共享资源；限流客户端随 lifespan 关闭 |
| 架构规则 | 现有架构边界测试与全量回归通过；阻止 Agent 导入的子进程测试通过 |

没有新增传统后端到 Agent 的运行依赖。源代码仍在同一仓库；两个入口应运行在各自进程中。现有 SQL 引擎配置是进程级单例，不能在同一进程装配不同数据库 URL 的两个应用。

为兼容既有迁移历史，独立库仍应用完整迁移链，其中会建立会话/记忆等闲置表；这不要求加载 Agent SDK 或启动 Agent。本阶段不重写迁移历史，也没有拆成两个 Git 仓库。

## 7. 下一项边界

当前证据证明独立启动、迁移和基础链路可用。尚不能据此宣称 MySQL 并发/死锁、多实例消费恢复或高吞吐全部验收。

下一份文档为 3/9：真实 MySQL 联调与并发证据，重点验证迁移 up/down、同用户并发点赞、多用户计数、取消幂等、outbox 同事务回滚，以及锁失败和多实例租约恢复。等待用户确认后实施。
