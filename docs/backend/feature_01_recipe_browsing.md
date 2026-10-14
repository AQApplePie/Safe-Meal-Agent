# 功能 01：食谱列表与详情交付文档

状态：实现、测试、架构审阅完成，等待用户确认下一项。日期：2026-10-08。

本次仅完成图中第一项 P0「食谱列表与详情」。后续点赞收藏、浏览历史、榜单、用户行为管理、行为事件处理均未开始。既有 Agent、鉴权、会话持久化和安全链路继续保留。

## 1. 已实现能力

- 公共列表 GET `/api/v1/recipes`：按食谱名称、菜系、难度、包含/排除食材、耗时和热量筛选，分页并排序。
- 公共详情 GET `/api/v1/recipes/{recipe_id}`：完整食材数量、单位归一化、烹饪步骤和营养信息。
- 列表返回轻量摘要；详情返回既有 Recipe 契约。公共共享目录允许匿名读取，无创建/修改/删除接口。
- Redis cache-aside；热点本地短缓存；同进程并发回源合并；缺失详情负缓存；随机 TTL；缓存异常回源。
- 新增独立 Alembic revision，只添加 3 个非唯一索引，未修改 migration 历史、未执行用户数据库迁移。

接口返回目录事实，食材排除是字面筛选；个性化过敏安全结论仍由原 Agent/Dietary 安全链负责，浏览接口不声称提供安全认证。

## 2. API 使用

默认前缀 `/api/v1`。查询示例：

```bash
curl 'http://localhost:8000/api/v1/recipes?name=鱼&max_total_time_minutes=30&offset=0&limit=10'
curl 'http://localhost:8000/api/v1/recipes?include_ingredients=土豆&exclude_ingredients=花生&sort_by=total_time&sort_order=asc'
curl 'http://localhost:8000/api/v1/recipes/1'
```

| 参数 | 类型/范围 | 默认/说明 |
|---|---|---|
| name | 1～255 字符 | 名称字面包含，SQL `%`、`_` 转义 |
| cuisine | 1～255 字符 | 菜系精确匹配 |
| difficulties | 重复参数，easy/medium/hard，最多 3 项 | 不限 |
| include_ingredients | 重复参数，最多 20 项，每项 1～100 字符 | 全部条件满足 |
| exclude_ingredients | 重复参数，最多 50 项，每项 1～100 字符 | 不含任何指定食材词 |
| max_total_time_minutes | 0～10080 | 不限 |
| max_calories | 0～100000，Decimal | 不限 |
| sort_by | name / total_time / total_calories | name |
| sort_order | asc / desc | asc |
| offset | 0～100000 | 0 |
| limit | 1～50 | 10 |

列表形状：

```json
{
  "items": [{"id": 1, "name": "蒸土豆", "description": "完整食谱", "total_time_minutes": 20, "servings": 2, "difficulty": "easy", "cuisine": "家常", "calories": "100.00"}],
  "total": 2,
  "offset": 0,
  "limit": 1,
  "has_more": true
}
```

Decimal 按既有 Pydantic 契约序列化为字符串。超范围、非法排序/枚举、非正整数 ID 返回 422；不存在的详情返回 404，沿用项目统一 `resource_not_found` 异常响应；数据库故障沿用统一 503。空列表及越界页为 200，total 保留真实匹配数量。

## 3. 查询与索引

复用 SqlAlchemyRecipeRepository：count + 当前页 + 批量食材 + 批量步骤，一页非空结果固定 4 次 SQL，避免逐菜 N+1。排序始终附加 `id ASC`，相同排序值翻页有稳定顺序；并发目录变更时，offset 分页不保证跨请求快照一致。

原初始化 schema 已有：名称唯一索引、菜系索引、食材关联 recipe_id 索引及步骤顺序唯一键。新增 revision `20261008_0007`，前序为 `20261001_0006`：

| 索引 | 列 | 用途 |
|---|---|---|
| ix_recipe_browse_time_id | total_time,id | 耗时排序/范围 |
| ix_recipe_browse_calories_id | total_calories,id | 热量排序/范围 |
| ix_recipe_browse_difficulty_name_id | difficulty,name,id | 难度筛选及名称排序 |

新迁移要求已存在 recipes 目录 schema，并先检查所有同名索引冲突，再创建索引；避免发现第二个冲突时先创建第一个。downgrade 仅删除这 3 个索引，保留食谱行。目标部署时按项目既有流程执行 `alembic upgrade head`；本次没有对用户数据库执行它。

`LIKE '%term%'` 含前导通配符，B-tree 不能使任意包含查询都高效命中；深 offset 仍有扫描成本。本次不宣称全筛选都走索引，也未引入 FullText/新检索平台。执行计划验证在 SQLite 通过；MySQL 实机优化器验证未执行，因为 Docker daemon 未启动。

## 4. Redis 与热点策略

配置：

```dotenv
RECIPE_CACHE_URL=redis://127.0.0.1:16379/1
RECIPE_CACHE_TTL_SECONDS=60
```

空 URL 表示关闭缓存，仍正常走 SQL。`.env.example` 已补齐，Docker app 使用 `redis://redis:6379/1`。连接/读取超时均为 0.2 秒，公共读取不要求模型配置。

| 项目 | 实现 |
|---|---|
| 列表 Key | `safemeal:recipes:v1:list:{SHA256(完整 RecipeQuery JSON)}` |
| 详情 Key | `safemeal:recipes:v1:detail:{id}` |
| 正常 TTL | 默认 60 秒 + 0～20% 抖动 |
| 缺失详情 TTL | 10 秒 + 0～2 秒抖动 |
| L1 | 每进程最多 256 条，1 秒固定过期；命中不延长有效期 |
| 单条缓存大小 | 256 KiB；超大结果正常返回但不缓存 |
| 回源合并 | 固定 64 条锁带，锁内二次检查；32 个并发相同详情测试仅一次仓储读取 |
| 故障策略 | Redis 不可达/损坏/无效 schema 回源；数据库异常传播，不缓存失败为无数据 |
| 生命周期 | 组合根共享仓储；关闭 Redis client 及 connection pool |

L1 降低热点 Redis 请求，锁带控制单进程回源。没有分布式锁：多进程同时冷启动/过期时仍可能每进程各回源一次。目录内容变更通过 TTL 最终刷新，默认最坏约 73 秒；新增食谱写入功能时需要配套失效策略。浏览接口只读，本轮没有新增写入/事件统计。

## 5. 架构审阅（测试后）

| 文件/层 | 审阅结论 |
|---|---|
| interfaces/http/routers/recipes.py | HTTP 校验与响应映射；阻塞服务在线程池执行；没有 SQL/Redis/模型实现导入 |
| interfaces/http/dependencies.py | 只从组合根获取已装配服务 |
| modules/recipe/contracts/browsing.py | 稳定领域响应 DTO；没有 FastAPI、Redis、配置或 Agent 依赖 |
| RecipeService / RecipeRepository | 复用现有业务与端口；没有新增查询业务框架 |
| infrastructure/cache/recipe_repository.py | 实现现有仓储端口的装饰器，缓存静态目录结果，未缓存 Agent 回答或执行状态 |
| infrastructure/persistence/recipe_repository.py | SQL 字面包含转义；既有参数化查询和批量聚合保持 |
| 新 migration | 只新增索引，不重写历史、不改食谱数据 |
| application_container.py | 唯一装配点；读服务与 Agent 服务共用同一仓储；读服务不初始化 LLM/外部来源；资源关闭明确 |
| tests/refactor/test_http_surface.py | 扩展只读 recipes 契约，保留所有 auth/chat/knowledge 契约断言 |

审阅发现并修复：列表不得静默过滤非规范 Recipe 对象；增加缓存单值上限；覆盖热点命中不滑动延长 TTL；使用显式 ConnectionPool 绕开当前 Redis.from_url 错误类型注解并管理资源。修复后完整回归再次通过。

架构自动约束 11 项全部通过，包含 modules 不依赖 Agent、业务模块不依赖配置/框架/组合根、基础设施只能由基础设施/组合根引用、原内外图仍独立。

## 6. 测试证据

环境：既有 agent_env Python 3.12，真实 SQLAlchemy SQLite、真实本机 Redis。Redis 由测试创建在短路径 /tmp 下，禁用持久化、不开 TCP，仅使用私有 Unix socket；清理只针对测试自建实例。没有操作现有 Redis/用户数据库。

| 检查 | 结果 |
|---|---|
| 执行前基线 | 253 passed / 1 skipped |
| 新增功能 | 27 项通过 |
| 全项目最终回归 | 280 passed / 1 skipped / 0 failed |
| 架构约束单独复核 | 11 passed |
| Ruff safemeal/tests | PASS |
| mypy safemeal | PASS，270 个源码文件 |
| 新增 5 个 Python 文件格式 | PASS |
| git diff --check | PASS |
| 实际应用启动/关闭及浏览接口 | PASS；开启 LLM 配置时读取仍不初始化模型 |
| MySQL 实机 EXPLAIN | NOT EXECUTED，Docker daemon 未启动 |

覆盖：SQL 筛选/字面通配符/稳定排序/分页/4次查询，列表摘要与完整详情，参数 422/缺失 404，跨实例 Redis 命中与过滤分页隔离，32并发热点，负缓存与 TTL，L1 固定新鲜度/容量，缓存损坏及二进制编码，Redis故障回源，数据库失败不缓存，超大值不缓存，索引升降级/冲突预检/SQLite 执行计划，原 Agent 安全/多轮/预算/审批/SSE 全量回归。

日志：`evaluation_results/backend_feature_01_iterations.json`；JUnit：`evaluation_results/backend_feature_01_pytest.xml`。环境限制、首次失败及修复均保留，没有删除失败记录。

## 7. 用户确认点

这一项的实现、测试与架构审阅已完成。真实 MySQL 执行计划与生产迁移仍是部署前事项。请确认是否开始第二项 P0「点赞与收藏」（幂等、唯一约束、并发一致性）；确认前不会开始该项。
