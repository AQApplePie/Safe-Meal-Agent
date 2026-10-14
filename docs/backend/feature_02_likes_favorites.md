# 第二项：点赞与收藏交付

日期：2026-10-08。范围：点赞、取消点赞、收藏、取消收藏，以及单个食谱的本人状态和当前租户计数。第三项尚未开始。

## 接口与使用

所有接口复用已有 Bearer 登录/OIDC 认证，身份仅来自认证 Principal。没有请求体；传入 user_id、tenant_id、subject 不会改变操作人。食谱目录仍为公共只读接口。

| 方法 | 路径（前缀 /api/v1） | 行为 |
|---|---|---|
| PUT | /recipes/{recipe_id}/like | 设为已点赞 |
| DELETE | /recipes/{recipe_id}/like | 设为未点赞 |
| PUT | /recipes/{recipe_id}/favorite | 设为已收藏 |
| DELETE | /recipes/{recipe_id}/favorite | 设为未收藏 |
| GET | /recipes/{recipe_id}/interaction | 读取本人状态与同租户计数 |

成功返回 200：`{"recipe_id":1,"liked":true,"favorited":false,"like_count":1,"favorite_count":0}`。

PUT/DELETE 是设置目标状态，重复调用幂等。点赞和收藏互不影响。不存在的食谱统一 404（包含取消操作），非正整数 ID 为 422，未认证为 401，不支持的身份长度为 403。tenant_id 为 1–100 字符，subject 为 1–255 字符；本地账号及符合这些长度的 OIDC subject 均可用。

```bash
curl -X PUT http://localhost:8000/api/v1/recipes/1/like \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl http://localhost:8000/api/v1/recipes/1/interaction \
  -H "Authorization: Bearer $ACCESS_TOKEN"
curl -X DELETE http://localhost:8000/api/v1/recipes/1/like \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

## 数据、幂等与并发

新增 `recipe_reactions` 表，复合主键 `(tenant_id, subject, recipe_id, kind)` 就是唯一约束；kind 仅允许 like/favorite。tenant/subject 分列防止拼接键碰撞；MySQL 8 使用 `utf8mb4_0900_bin` 区分大小写和尾部空格。created_at 由数据库生成，重复点赞/收藏不重写时间。recipe_id 外键指向现有 recipes，食谱删除级联清理行为。没有 users 外键，以支持已有 OIDC 身份。

MySQL PUT 使用 ON DUPLICATE KEY UPDATE 的无变化更新；SQLite 使用只针对该主键的 ON CONFLICT DO NOTHING，不使用会吞掉其他约束异常的 INSERT IGNORE。DELETE 按完整身份和行为条件删除。

MySQL 写操作先 SELECT 食谱行 FOR UPDATE，再修改行为、单条聚合 SQL 计算本人状态和同租户计数，提交成功才返回。锁覆盖尚不存在的行为行，并让同一食谱的写入串行执行；后完成的相反目标状态操作决定最终状态。使用事务内事实计数，避免独立增减计数漂移；READ 的状态和计数也由同一条 SQL 获取。响应代表事务读取时的快照，之后其他请求仍可更新。

计数索引 `(tenant_id, recipe_id, kind)`，外键辅助索引 `(recipe_id)`。不经过公共 Recipe Redis 缓存，也不初始化模型或 Agent。数据库错误转换为项目已有应用异常，连接/操作故障由既有错误响应处理。

取舍：同一食谱的所有用户/租户写入争用同一食谱行，热点吞吐受限；计数会扫描对应行为索引区间，未引入预聚合计数或异步统计。后续榜单/事件项再评估这些需求。

## 迁移与回滚

新增迁移 `20261008_0008`，前置 `20261008_0007`。升级前检查 canonical recipes 存在、目标表不存在；升级只新增行为表和两个索引。未修改历史迁移，未对用户数据库执行迁移。

部署前备份、确认已有食谱目录及迁移基线，然后在目标环境运行：

```bash
alembic upgrade 20261008_0008
```

回滚到 `20261008_0007` 会删除 recipe_reactions 及本项行为数据，保留食谱/身份/会话；执行前应备份行为数据。MySQL 8.0/InnoDB 为项目当前目标，尚未在真实 MySQL 验证迁移和并发锁行为。

## 测试与修复

新增测试使用临时文件 SQLite、独立连接、多线程，以及真实登录令牌。完整回归中的 Redis 测试只启动自己的临时 Unix socket 实例，不操作用户基础设施。

覆盖：重复 PUT/DELETE、行为独立、时间保持、用户/租户/食谱隔离、大小写与分隔符身份、32次同身份并发、多用户并发、相反操作并发后的确定性最终状态、唯一键/外键/CHECK/级联删除、缺失食谱、HTTP 身份伪造、认证要求、真实两个账号登录隔离、超长身份、生产应用生命周期与无模型初始化、迁移升降级/冲突预检、MySQL DDL 编译。

首轮发现测试配置遗漏 DATABASE_URL、认证测试替身缺少方法；均已修复。类型检查发现两个 SQL 方言 Insert 类型冲突，改为公共 Insert 类型。架构审阅发现认证身份超长可能产生未映射的校验异常，增加 403 映射；MySQL 身份列采用 MySQL 8 NO PAD 二进制排序规则。

最终结果见本文件下方验证记录及 `evaluation_results/backend_feature_02_pytest.xml`。MySQL DDL 编译通过不代表 MySQL 实机执行通过；实机验证尚待具备服务的环境。

## 最终验证记录

| 检查 | 结果 |
|---|---|
| 上一项交付基线 | 280 passed / 1 skipped |
| 本项新增用例 | 17 passed |
| 审阅修复后完整回归 | 297 passed / 1 skipped / 0 failed |
| 本项与架构约束联合复核 | 28 passed（17 功能 + 11 架构） |
| Ruff safemeal/tests | PASS |
| mypy safemeal | PASS，279 个源码文件 |
| 本项 11 个 Python 文件格式 | PASS |
| git diff --check | PASS |
| 生产应用生命周期/错误映射/无模型初始化 | PASS |
| MySQL 实机迁移、并发及执行计划 | NOT EXECUTED，当前没有可用 MySQL 服务 |

## 测试后的架构审阅

| 层/文件 | 结论 |
|---|---|
| modules/interaction/contracts | 无技术实现依赖，稳定身份和返回 DTO |
| modules/interaction/application | 仅校验与编排端口，不依赖配置/Agent/基础设施 |
| modules/interaction/ports | 事务边界由仓储实现，协议不暴露 Session 或 SQL |
| infrastructure/persistence/reaction_repository.py | SQL、事务、约束、错误映射均在适配器中；复用 canonical recipes 和既有 Engine |
| db/models/__init__.py | 为 Alembic 注册行为表，保留现有模型；直接引用食谱列解决既有双 metadata 的外键解析 |
| interfaces/http/routers/interactions.py | 认证、参数/响应映射、线程池适配，不直连数据库 |
| application_container.py / dependencies.py | 组合根装配服务，接口只索取服务；无 Agent/模型初始化 |
| 新迁移 | 独立增量、显式预检、只删除本项表的降级 |
| 既有公共目录接口/缓存 | 个性化行为另行查询，公共缓存不携带个人状态 |

架构依赖约束复核通过。未新增 Agent Tool、Graph 节点、浏览历史、排行榜、MQ 或个人收藏列表。

## 用户确认

本项完成实现、测试与架构审阅后交付。请确认是否开始第三项 P1「浏览历史」（高频写入、去重、历史排序）。确认前不开展第三项。
