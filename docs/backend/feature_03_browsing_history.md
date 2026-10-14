# 第三项：浏览历史交付

日期：2026-10-08。范围：已认证用户记录食谱浏览，以及读取去重后的最近浏览列表。第四项尚未开始。

## 1. 接口与使用方式

| 方法 | 路径（前缀 /api/v1） | 用途 |
|---|---|---|
| PUT | /recipes/{recipe_id}/view | 记录一次实际浏览；同用户同食谱更新最近时间 |
| GET | /recipes/history?limit=20&cursor=... | 读取本人最近浏览；默认 20，最多 50 条 |

两个接口都复用已有 Bearer 登录/OIDC 认证。tenant_id/subject 来自认证 Principal，不接受客户端身份或浏览时间。身份长度沿用第二项：tenant_id 1–100 字符、subject 1–255 字符。食谱 ID 限制在现有数据库 INT 范围 1–2147483647。

浏览记录单独上报：调用方在成功展示食谱后请求 PUT /view；读取公共食谱详情、获取历史列表均不会隐式写入历史。本轮交付后端接口，现有聊天前端没有新增历史页面或自动上报。

上报成功返回 200：

```json
{"recipe_id":1,"recipe_name":"食谱1","last_viewed_at":"2026-10-08T09:00:00.123456Z"}
```

历史列表成功返回 200：

```json
{
  "items":[{"recipe_id":1,"recipe_name":"食谱1","last_viewed_at":"2026-10-08T09:00:00.123456Z"}],
  "has_more":false,
  "next_cursor":null
}
```

列表名称读取当前食谱目录，不复制食谱全文。上报不存在的食谱返回 404；未认证 401；不支持的身份长度 403；无效 ID/limit/cursor 422；数据库故障由项目既有处理返回 503。

```bash
curl -X PUT http://localhost:8000/api/v1/recipes/1/view \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl 'http://localhost:8000/api/v1/recipes/history?limit=20' \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

有下一页时将 next_cursor 原样传回 cursor；刷新列表时不传 cursor。

## 2. 高频写入、去重与时间

新增 `recipe_view_history` 表，主键 `(tenant_id, subject, recipe_id)`：每个用户每道食谱最多一行。重复浏览更新最近时间，不创建无限追加日志，不累计次数。不同账号/租户分列隔离，MySQL 8 身份列使用 utf8mb4_0900_bin。

写入使用数据库原子 upsert：MySQL ON DUPLICATE KEY UPDATE；SQLite ON CONFLICT DO UPDATE，只针对复合主键。时间来自数据库而非客户端或各应用进程的时钟：MySQL UTC_TIMESTAMP(6)、DATETIME(6)；SQLite UTC 毫秒精度，统一补齐六位小数字符格式，与 DateTime 查询参数保持一致。

更新取已有时间与新时间较大值，防止数据库时钟回退或较早请求后执行导致历史倒退。同一主键的并发写入由数据库处理；没有应用内去重集合或进程锁，不锁定整个食谱来串行不同用户的浏览。写入在短事务内执行三个语句：查询食谱 ID/名称存在性、upsert、读取本次事务后的时间；提交成功才返回。

本项优化的是历史行数、索引访问与查询次数。没有时间窗口节流：每次有效浏览仍同步上报并尝试写库，保证最近时间及时更新。同一用户同一食谱极高频写入仍会争用该行；SQLite 自身串行写入不能代表 MySQL 生产吞吐。没有新增 Redis 缓冲、MQ、计数或异步批处理，这些属于后续榜单/事件项。

保留策略：每个不同食谱一条历史，未自动按天过期/裁剪，也未新增清空接口；存储随“用户 × 浏览过的不同食谱”增长，不随重复浏览次数增长。食谱删除通过外键 ON DELETE CASCADE 清理对应历史。身份同时支持本地账号与 OIDC，不建立 users 外键。

## 3. 排序与游标分页

排序为 `last_viewed_at DESC, recipe_id DESC`；同一时间多道食谱通过 ID 保证确定性。索引 `(tenant_id, subject, last_viewed_at, recipe_id)` 支持过滤和反向扫描，额外 recipe_id 索引用于外键及删除。

列表用一条 JOIN 读取当前食谱名称和历史，查询 limit+1 判断 has_more，省去全量 COUNT 和逐条食谱查询。游标仅编码时间和食谱 ID，业务服务验证长度（最多 256）、Base64、结构、带时区时间和 ID 范围；每次查询始终独立绑定当前认证身份。跨账号拿到别人的游标也不能读取其历史。

采用位置分页，不采用 offset。它不是跨请求冻结快照：两页间若未读取的食谱被再次浏览并移到游标之前，本次后续页不会包含它；从第一页刷新即可看到最新记录。已读边界不会因重访而重复出现在更早的后续页。测试覆盖此行为。

## 4. 增量迁移

迁移 `20261008_0009` 前置 `20261008_0008`。升级前预检 canonical recipes 存在、目标历史表不存在。升级仅添加历史表和两个索引，不修改旧迁移、不改点赞收藏或食谱事实。

没有对用户数据库执行迁移。部署环境先备份、检查迁移版本与 MySQL 8/InnoDB 食谱目录，再执行：

```bash
alembic upgrade 20261008_0009
```

回滚至 `20261008_0008` 只删除本项历史表及其数据，保留食谱、点赞收藏、身份和会话；回滚前需保存历史数据。SQLite 已验证升级/降级和冲突预检。Docker daemon 当前未启动，MySQL 实机迁移、执行计划与多连接并发尚未验证；MySQL DDL 编译不能替代实机验证。

## 5. 测试与修复记录

上一项交付基线：297 passed / 1 skipped。新增 21 个浏览历史用例使用真实临时文件 SQLite、独立连接和线程池；真实本地注册/登录令牌验证两账号隔离。完整回归中的 Redis 只使用测试自建临时 Unix socket 实例。

覆盖：重复浏览去重、回访置顶、UTC 时间、时间回退保护、相同时间的 ID 排序、连续游标分页、实际写入时间的分页边界、多用户/租户/大小写/尾空格/分隔符隔离、48 次同食谱并发、64 次跨食谱并发、分页期间回访、无效游标/参数、缺失食谱不写入、唯一键/外键/级联删除、SQL 查询预算和索引计划、数据库故障、HTTP 身份/时间伪造、无认证及超长身份、真实令牌与跨账号游标、生产应用生命周期和错误映射、无模型/目录缓存初始化、迁移升降级/冲突和 MySQL DDL 编译。

首轮 17 passed / 1 failed：实际 SQLite 写入的毫秒字符串与查询时六位小数参数不一致，导致分页边界重复。修复为统一六位格式；修复过程中一次编辑错误把 literal 导入加入 Column 参数，收集/类型检查立即发现并已纠正。新增边界回归测试保留。

首轮全量通过后完成架构审阅，将共用 get_interaction_actor 从点赞路由移至 authentication，消除历史路由对其他路由的依赖；保持第二项身份校验行为。审阅后再次执行完整回归。

| 检查 | 最终结果 |
|---|---|
| 新增浏览历史用例 | 21 passed |
| 历史 + 点赞收藏 + 架构 + HTTP 契约 | 52 passed |
| 全项目回归 | 318 passed / 1 skipped / 0 failed |
| Ruff safemeal/tests | PASS |
| mypy safemeal | PASS，284 个源码文件 |
| 本项新增 7 个 Python 文件格式 | PASS |
| git diff --check | PASS |
| 读取/写入 SQL 预算 | 1 / 3 个语句，通过 |
| SQLite 排序索引计划 | 命中 ix_recipe_history_recent，无临时排序 |
| MySQL 实机验证 | NOT EXECUTED：Docker daemon 未启动 |
| 用户数据库迁移 | 未执行 |

机器记录：`evaluation_results/backend_feature_03_iterations.json`；JUnit：`evaluation_results/backend_feature_03_pytest.xml`。

## 6. 测试后的代码与架构审阅

| 文件/层 | 审阅结论 |
|---|---|
| modules/interaction/contracts/history.py | 精简历史 DTO、带时区位置、分页响应，无身份授权信息混入游标 |
| modules/interaction/application/history_service.py | 验证/解析分页位置与编排端口，不依赖 FastAPI、SQL、Redis、配置、Agent |
| modules/interaction/ports/history_repository.py | 去重写入及有界读取协议，未暴露事务/连接技术类型 |
| infrastructure/persistence/history_repository.py | SQL、upsert、数据库 UTC 时间、索引排序、错误映射均在基础设施；复用既有 Engine、Base 和 canonical recipes |
| infrastructure/persistence/db/models/__init__.py | 注册历史 metadata 供 Alembic 使用，跨 metadata 外键沿用第二项直接列引用 |
| interfaces/http/authentication.py | 已认证 Principal 转交互身份的共用依赖，第二/三项复用同一长度校验 |
| interfaces/http/routers/history.py | 参数/响应适配及线程池调用，未直接引用基础设施，未改变公共 GET 的副作用 |
| interfaces/__init__.py | 注册静态 /recipes/history 在 /recipes/{recipe_id} 前，避免路由被动态详情捕获 |
| dependencies.py / application_container.py | 唯一组合根创建与复用 HistoryService，无模型、Agent、公共缓存初始化 |
| 新 migration | 独立增量、预检、只删除本项表的降级 |
| tests/refactor/test_http_surface.py | 保留既有 auth/chat/knowledge/公共 recipes 断言，并约束 history GET 和 view PUT |

11 项现有架构自动约束通过；原 Agent 工作流未修改，公共目录缓存未保存个人历史。第四项排行榜、第五项行为批量管理及第六项 MQ 不在本次实现中。

## 7. 下一项确认

第三项已完成实现、测试与架构审阅。请确认是否开始第四项 P1「热门食谱榜单」（Redis ZSet、异步统计、数据恢复）。确认前不开始第四项。
