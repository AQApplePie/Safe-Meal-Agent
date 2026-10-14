# 第四项：热门食谱榜单交付

日期：2026-10-08。范围：今日热门、最受欢迎、Redis ZSet、定时异步统计、缓存损坏/丢失恢复。第五项尚未开始。

## 1. 统计口径与接口

榜单复用当前认证身份，始终限定当前租户；没有客户端 tenant_id 授权参数。

| mode | 用户能力 | 分数 |
|---|---|---|
| today（默认） | 今日热门 | 当天浏览该食谱的独立用户数 |
| popular | 最受欢迎 | 当前有效点赞数 + 当前有效收藏数 |

今日默认按 Asia/Shanghai 的自然日计算，数据库中的 UTC 时间换算为对应起止范围；起点包含、终点不包含。重复浏览同一食谱不会重复计分。popular 是行为数，不是独立人数，同一用户同时点赞和收藏贡献 2 分；取消行为会在后续统计中扣除。0 分食谱不入榜，同分按 recipe_id 降序稳定排序。

今日口径使用第三项的“每用户每食谱最近浏览事实”，不保存原始 PV 事件或历史每日榜单，因此当前日可重建，往日完整日榜不在本项范围。

```http
GET /api/v1/recipes/rankings?mode=today&offset=0&limit=20
Authorization: Bearer <access_token>
```

mode 可取 today/popular；limit 默认 20，范围 1–50；offset 从 0 开始，必须小于配置的榜单容量（默认 1000）。接口只有 GET，没有对外刷新、修改分数或全租户查询接口。

```json
{
  "mode":"today",
  "day":"2026-10-08",
  "updated_at":"2026-10-08T04:00:00Z",
  "source":"redis",
  "items":[{"recipe_id":1,"recipe_name":"食谱1","score":3,"rank":1}],
  "ranked_count":1,
  "has_more":false,
  "truncated":false
}
```

popular 的 day 为 null。updated_at 表示该快照开始构建的 UTC 时间，source 表示 redis/database。ranked_count 是本快照保留的榜单条数，超过容量时 truncated=true；它不是全库食谱总数。rank 为实际榜单位置，分页间刷新可能改变位置，跨请求不保证固定快照。

未认证 401；不支持的身份 403；无效参数 422。Redis 故障有数据库回退；数据库也不可用且没有有效缓存时返回既有 503，不伪造空榜单。已有聊天前端未新增榜单页面，本项交付后端接口。

## 2. 数据事实与 Redis ZSet

复用已有 recipe_view_history、recipe_reactions 和 canonical recipes；不新增点赞/浏览事件表或 SQL 计数副本。SQL 用 GROUP BY 聚合绝对分数，JOIN 目录一次获取名称，并读取容量+1 判断截断。

Redis 为每租户、配置、模式和日期保存：

- scores：ZSet，成员为补齐 10 位的食谱 ID，分数为绝对统计值。
- names：Hash，与 ZSet 成员对应的食谱名称。
- meta：快照时间、模式、日期、条数和截断标志。

通过 ZREVRANGE 获取分数降序列表；补齐 ID 使 Redis 同分字典序与 SQL 的数字 ID 降序一致。Lua 一次原子读取 metadata、分数和名称，不会读到不同代快照的组合。返回最多 50 个成员，Redis 热读不查询 SQL。

key 前缀为 safemeal:rankings:v1；租户用 SHA-256 作为 Redis hash tag，时区与容量配置的哈希隔离不同统计配置，避免配置切换复用旧口径。不会把原始 tenant/subject 写入 key。名称和分数不混入第一项公共食谱缓存。

## 3. 异步统计与多进程一致性

配置 Redis 地址后，FastAPI lifespan 启动一个 RankingWorker：启动即刷新，此后每周期分批发现已有浏览/点赞收藏事实的租户。默认每 30 秒处理最多 50 个租户，按租户游标循环；统计通过 asyncio.to_thread 执行，不阻塞事件循环。

浏览/点赞/收藏写入仍只提交数据库，不等待 Redis；榜单最终与事实一致。后台按绝对分数覆盖快照，重复刷新或重试不会重复累加，因此不使用 ZINCRBY 或未经去重的客户端事件。

每租户/配置先取得 SET NX EX 的 120 秒租约。临时 ZSet/Hash/meta 通过 pipeline 准备并设置 TTL；发布 Lua 再次检查租约 token、临时成员数量，然后一次切换正式快照与 TTL。旧任务租约失效后不能覆盖新任务结果，也不能删除其他任务的租约。临时键失败后清理，进程中断时由 TTL 清理。发布失败停止该租户后续模式处理，下一轮从事实重试。

失败不会退出整个后台循环；数据库异常记录日志后下一周期重试。Redis 异常允许跳过刷新，HTTP 可以读取数据库。Redis Lua 使用注册脚本，脚本缓存丢失时自动重新加载。

应用关闭先停止并等待当前后台批次，再关闭 Redis 连接池和数据库资源，避免后台线程继续使用已关闭连接。关闭会等待正在执行的 SQL 完成；未新增数据库语句执行超时机制。

## 4. 恢复与可见性边界

| 情形 | 行为 |
|---|---|
| 冷启动/未生成快照 | HTTP 即时 SQL 聚合；后台下一轮生成 Redis 快照 |
| Redis 重启、清空或键过期 | 数据库事实仍在，HTTP 回退；后台自动全量重建 |
| ZSet/Hash/meta 部分丢失、类型错误、无效分数/元数据 | 检测后视为缓存未命中，回退并等待重建 |
| 数据库暂时不可用，已有有效 Redis 快照 | TTL 内继续提供快照，响应展示 updated_at |
| Redis 与数据库均不可用 | 返回 503 |
| 日期切换 | 使用新日期 key，不会返回上一日榜单；首次请求可由 SQL 得到新榜 |
| 取消点赞/收藏或食谱删除 | 下一轮刷新更新分数/移除食谱；缓存可能短暂保留旧状态 |
| 租户所有历史/行为事实都被清空 | 不再被 SQL 租户发现选中；原快照最迟在 TTL 到期后失效 |

默认快照 TTL 为 300 秒；活跃租户的更新时间取决于批次轮转和聚合耗时，不能保证所有租户每 30 秒刷新。租户数较多时需调整批次/周期/TTL。取消行为的本人状态仍由第二项直接读取 SQL；排行榜允许异步延迟。

容量限制只限制快照和返回数据，SQL 仍需统计对应事实行；没有生产规模压测。大租户重建、Redis 故障时每请求 SQL 聚合、每个应用进程的租户发现查询仍可能形成数据库压力，需要按部署负载评估。

## 5. 配置与迁移

| 环境变量 | 默认值 | 用途 |
|---|---|---|
| RECIPE_RANKING_REDIS_URL | 空 | 空时只提供 SQL 榜单，不启动 Redis 后台统计 |
| RECIPE_RANKING_REFRESH_SECONDS | 30 | 每批次后等待秒数，1–3600 |
| RECIPE_RANKING_TTL_SECONDS | 300 | 正式快照 TTL，1–86400 |
| RECIPE_RANKING_CAP | 1000 | 保留前 N 名，1–10000 |
| RECIPE_RANKING_TENANT_BATCH | 50 | 每轮租户数，1–1000 |
| RECIPE_RANKING_TIMEZONE | Asia/Shanghai | IANA 时区，配置时验证 |

.env.example 给出本机 Redis DB 2 地址；docker-compose 的应用设置 redis://redis:6379/2。榜单连接有 0.2 秒连接/读写超时。部署时配置地址并启动应用，后台自动开始刷新；恢复时无需手动更改数据库分数或公开刷新接口。

新增迁移 `20261008_0010`，前置 `20261008_0009`，只添加历史索引 `(tenant_id, last_viewed_at, recipe_id)`，支持按租户/日期聚合。原历史排序索引与点赞计数索引保留。预检历史表存在、新索引不存在，不修改历史迁移。

没有对用户数据库执行迁移。部署前检查备份与当前迁移基线，再运行：

```bash
alembic upgrade 20261008_0010
```

回滚至 20261008_0009 只删除本项索引，保留浏览、点赞收藏和食谱数据。SQLite 已验证升降级及数据保留。Docker daemon 当前未启动，MySQL 实机迁移、执行计划和生产并发/吞吐尚未验证。

## 6. 测试与迭代

基线：上一项交付 318 passed / 1 skipped。本轮新增 25 项榜单测试，使用真实 SQLAlchemy 临时 SQLite、真实测试专属 Redis Unix socket、真实应用生命周期和后台线程。

覆盖：统计口径、同分数字排序、租户隔离、分页/容量、上海日期边界和跨日、分批租户发现、SQL 单查询和日索引计划、真实 ZSet、重复绝对刷新不累加、取消行为刷新、Redis 丢失重建、分数/名称/元数据损坏、错误类型/小数分数、Redis 故障回退、双故障异常、租约互斥/失效旧写入/错误释放、空快照与 TTL、真实二进制 Redis 客户端、配置命名空间、脚本缓存丢失、SQL 故障时缓存可读、全部事实清空后的 TTL 失效、并发原子读取、后台失败重试/关闭、HTTP 鉴权/伪造租户参数、迁移索引升降级且保留数据、生产应用启动后异步接收取消点赞变化、无模型/食谱缓存初始化。

首轮新增功能 21 passed；类型检查发现当前 Redis eval 注解与实际 API 不符，以及 mode 元组类型推断问题。改用注册脚本的 keys/args 调用和显式 RankingMode 元组；mypy 通过。首轮完整回归 339 passed / 1 skipped。

测试后审阅补充：配置口径隔离、Hash/ZSet 数量校验、发布失败停止该租户后续重建、只读 HTTP 契约，新增 4 项边界测试；真实异步取消点赞更新也在生产 lifespan 用例中验证。最后再次完整回归。

| 检查 | 结果 |
|---|---|
| 新增榜单用例 | 25 passed |
| 榜单 + 架构 + HTTP 契约复核 | 39 passed（25 + 11 + 3） |
| 全项目最终回归 | 343 passed / 1 skipped / 0 failed |
| Ruff safemeal/tests | PASS |
| mypy safemeal | PASS，291 个源码文件 |
| 新增 9 个 Python 文件格式 | PASS |
| git diff --check | PASS |
| Redis ZSet/Lua/租约/损坏恢复/原子读 | PASS，真实 Redis |
| MySQL 实机/生产规模压测 | NOT EXECUTED |
| 用户数据库迁移 | 未执行 |

日志：`evaluation_results/backend_feature_04_iterations.json`；JUnit：`evaluation_results/backend_feature_04_pytest.xml`。

## 7. 测试后的架构审阅

| 文件/层 | 结论 |
|---|---|
| modules/interaction/contracts/ranking.py | 快照、分页、排序项稳定契约，无 Redis/SQL/HTTP 类型 |
| modules/interaction/ports/ranking.py | 统计事实与快照存储分别为端口，业务不引用具体技术 |
| modules/interaction/application/ranking_service.py | 统一口径、自然日、容量、回退及刷新编排，不依赖框架/配置/Agent |
| infrastructure/persistence/ranking_repository.py | 聚合、租户发现、JOIN 名称、SQL 异常映射在适配器内 |
| infrastructure/cache/ranking_store.py | ZSet/Hash、租约、脚本、临时键与故障回退均在基础设施 |
| infrastructure/cache/ranking_worker.py | 生命周期后台轮询适配，线程池执行统计，失败重试与关闭明确 |
| infrastructure/persistence/history_repository.py | 只注册新增日期索引，已有写入/分页行为保持 |
| interfaces/http/routers/rankings.py | 复用认证 Actor、线程池调用用例，不直连 SQL/Redis |
| interfaces/__init__.py | 静态 rankings 路由在动态 recipe_id 详情前注册 |
| application_container.py / dependencies.py | 唯一装配点，配置命名空间、连接池和 Worker 生命周期集中管理 |
| main.py | lifespan 启动/关闭委托组合根，无统计业务规则 |
| 新 migration | 独立增量，只加/删索引，无业务数据改写 |
| tests/refactor/test_http_surface.py | 扩展 rankings GET 契约，保留原接口断言 |

11 项自动架构约束通过。原 Agent 图、模型、浏览写入和点赞收藏语义未改；未提前引入第五项批量行为管理或第六项 MQ 消费系统。

## 8. 用户确认

第四项已完成实现、测试与架构审阅。请确认是否开始第五项 P1「用户身份与行为管理」（鉴权、数据隔离、批量查询，包含个人收藏列表）。确认前不开始第五项。
