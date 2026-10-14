# 第五项：用户身份与行为管理交付

日期：2026-10-08。范围：审查复用现有登录/认证，补齐个人收藏列表和批量交互状态查询，验证身份与数据隔离。第六项尚未开始。

## 1. 本项结果

复用已有 AuthService、身份持久化与 Principal，不新增账号体系。新增两个认证接口，扩展既有 InteractionService / ReactionRepository；个人行为仍直接读 SQL，不放入公共食谱缓存或 Redis 榜单快照。

| 方法 | 路径（前缀 /api/v1） | 能力 |
|---|---|---|
| GET | /recipes/favorites?offset=0&limit=20 | 本人收藏列表 |
| POST | /recipes/interactions/query | 批量读取本人点赞/收藏状态及同租户计数 |

既有注册、登录、refresh、logout、/auth/me 保留。原点赞/收藏写入、历史、榜单及 Agent 工作流不变。没有新增管理员接口、个人资料编辑、账号删除或前端页面。

## 2. 登录与鉴权审查

| 能力 | 现有行为与审查结论 |
|---|---|
| 注册 | 邮箱规范化、密码规则、Argon2 哈希；租户由服务配置决定，额外身份字段被请求契约拒绝 |
| 登录 | 验证密码及账号 active 状态，必要时重新哈希密码 |
| 本地 Access JWT | 校验签名、固定算法、issuer/audience、到期、token 类型；再读数据库验证 user/tenant/status/token_version |
| 本地身份读取 | /auth/me 只读取当前认证身份；不接受任意用户 ID |
| Refresh | 已有轮换及重放检测；重放撤销令牌族并增加 token_version，使旧 access 失效 |
| Logout | 保留已有策略：撤销提交的 refresh token；已签发 access 在到期前仍有效（默认 15 分钟）。客户端应同时清除本地令牌 |
| 禁用/锁定账户 | 本地 access 校验读取当前账号状态，立即拒绝其受保护请求 |
| OIDC | 校验签名、允许算法、issuer/audience、exp/iat/sub；OIDC 模式关闭本地登录/注册等端点 |

本项修复两个 OIDC 问题：

1. 原来每请求构造 PyJWKClient，JWKS 集合缓存无法跨请求复用。现在按 JWKS URL 复用最多 8 个客户端，集合缓存明确为 300 秒；未知 kid 仍通过 PyJWT 刷新，测试验证密钥轮换。
2. 原来 str(sub)/str(tenant) 和 tenant.strip() 可能把非字符串或不同身份映射成已有身份。现在 subject 必须是非空白字符串；tenant 必须是非空白字符串，并保留签发值的原样身份（包括尾部空格）。无效 subject 返回 401，无效 tenant 返回 403；交互存储不支持的长度仍返回 403。

OIDC 信任由签发方和配置的 issuer/audience/JWKS 决定，不使用本地账号状态替代外部身份。JWKS 缓存遵循上述有效期；没有新增在线 token introspection 或即时外部账号撤销机制。

原来经 strip 归一化的异常 OIDC tenant 值，现在不会再与正常 tenant 共享行为。没有自动改写历史数据；签发方应提供预期的规范 tenant 值。

另外修复会话/记忆的身份存储键：原 `tenant:subject` 拼接对含分隔符的身份存在碰撞，而且大小写/Unicode 原值不适合不区分大小写的存储比较。普通小写 ASCII 身份（a–z、0–9、下划线、连字符）且合成键不超过 255 字符时保留原键，兼容默认本地 UUID 账号；其他身份使用 tenant/subject JSON 元组的 SHA-256 编码，生成不含冒号、长度固定的键，避免与普通旧键重合。

这项修复同时作用于既有聊天和长期记忆 HTTP 身份绑定，不修改 Agent 图。特殊身份原来存于旧键下的会话/记忆不会自动迁移或回退查询，避免重新引入身份混用；需要确认记录归属后另行迁移。没有删除或改写这些用户数据。收藏/点赞/历史仍使用分列身份，不受存储键编码影响。

## 3. 个人收藏列表

```http
GET /api/v1/recipes/favorites?offset=0&limit=20
Authorization: Bearer <access_token>
```

offset 为 0–10000，limit 为 1–50（默认 20）。只读取当前 `(tenant_id, subject)` 的 favorite 行，JOIN 当前食谱名称；按 created_at DESC、recipe_id DESC 排序。重复收藏保留原创建时间，取消后重新收藏生成新时间。点赞不会进入收藏列表。

```json
{
  "items":[{"recipe_id":2,"recipe_name":"食谱2","favorited_at":"2026-10-08T12:00:00"}],
  "offset":0,
  "limit":20,
  "has_more":false
}
```

favorited_at 保留已有反应表中的数据库创建时间；原列是无时区 DateTime，响应不冒充带 UTC 时区的时间。排序使用同一数据库存储时间。

使用 limit+1 判断下一页，不查询全量 COUNT。收藏取消或食谱删除后，后续 SQL 查询立即不再返回该记录。offset 分页期间发生新增/删除可能引起位移，刷新第一页即可更新；本项不保证跨请求固定快照。

## 4. 批量交互查询

```http
POST /api/v1/recipes/interactions/query
Authorization: Bearer <access_token>
Content-Type: application/json

{"recipe_ids":[2,1,999,2]}
```

单次 1–100 个 ID，必须为 JSON 整数，范围 1–2147483647；拒绝 bool、字符串、越界 ID 和额外请求体字段。重复 ID 去重，响应保持首次出现的输入顺序。

```json
{
  "items":[
    {"recipe_id":2,"liked":false,"favorited":true,"like_count":0,"favorite_count":1},
    {"recipe_id":1,"liked":false,"favorited":false,"like_count":0,"favorite_count":0}
  ],
  "missing_recipe_ids":[999]
}
```

存在但没有行为的食谱返回两个 false 和两个 0；不存在的目录 ID 单独列出。liked/favorited 是本人状态，两个 count 是同租户所有用户当前有效行为数，不泄露其他租户计数。接口只读，不触发浏览记录、榜单计分或任何写入。

SQL 对指定 ID 集合一次条件聚合，并 LEFT JOIN canonical recipes；无行为时 COALESCE 为 0。没有逐个调用 read()、公共 RecipeService 或完整食谱加载。

## 5. 数据隔离与查询开销

所有个人读/写从同一个 get_interaction_actor 依赖获得身份；tenant/subject 分列，不能通过请求路径、query 或 body 选择其他用户。批量请求体额外字段直接 422；收藏列表中不受支持的身份 query 参数不会改变主体。

两种新增查询各执行 1 条业务 SQL。使用本地身份时，鉴权额外读取账号状态，因此请求通常还有 1 条身份 SQL；保留此读取使禁用和 token_version 失效及时生效。业务查询次数不会随 100 个 ID 或 50 个收藏逐项增长。

收藏索引 `(tenant_id, subject, kind, created_at, recipe_id)` 支持个人范围和最近排序；批量计数复用既有 `(tenant_id, recipe_id, kind)` 索引。SQL SQLite 执行计划已验证收藏排序不使用临时排序。

数据读取是当前 SQL 语句的快照，之后其他请求仍可修改。个人行为没有 Redis 缓存，新状态与第四项允许异步延迟的排行榜独立。

## 6. 迁移与部署

新增迁移 `20261008_0011`，前置 `20261008_0010`；只添加收藏排序索引，预检反应表存在及目标索引未存在，不改变旧迁移或业务数据。

没有对用户数据库执行迁移。部署前检查备份和版本基线，再执行：

```bash
alembic upgrade 20261008_0011
```

回滚至 20261008_0010 只删除本项索引，保留收藏、点赞、历史、身份和食谱数据。现有数据库必须先具有前几项表。无需新增 Redis、MQ 或身份服务配置。

Docker daemon 当前未启动，MySQL 实机迁移和执行计划未验证；未访问线上 OIDC 服务。

## 7. 测试记录

上一项基线：343 passed / 1 skipped。本项新增 34 个用例，使用真实临时 SQLite、真实 Argon2/JWT、本地 RSA 签名 OIDC token。JWKS HTTP 响应由测试拦截，仍完整运行 PyJWT 密钥选择、签名、issuer/audience/exp 校验与缓存轮换；没有外网请求。

覆盖：收藏排序/同时间 ID 排序/分页、取消与重新收藏、无数据、用户/租户隔离、批量输入顺序/去重/缺失与零状态、100 ID 单查询预算、收藏索引计划、参数界限与 strict JSON ID、食谱级联删除、真实注册/登录/me、两账号私有收藏与取消隔离、身份伪造、过期/错误 tenant/audience/issuer/type 令牌、禁用账号/token_version、refresh 重放与 logout 既有契约、有效 OIDC 及 JWKS 跨请求复用、无效 subject/tenant 和身份原样保留、未知 kid 轮换、本地身份端点在 OIDC 模式关闭、索引升降级保留数据、生产应用装配与错误映射、无 LLM/目录缓存初始化，以及会话身份分隔符/大小写/Unicode/长度隔离、默认键兼容和真实签名 OIDC 的聊天主体绑定。

首轮新增测试 31 passed；Ruff 发现测试中未用导入并移除。补充生产生命周期/DB 故障用例后，首轮全量 375 passed / 1 skipped。测试后架构审阅补充 HTTP 契约，明确 JWKS 缓存寿命，并修复会话/记忆身份键碰撞（新增 2 项回归）；再次完成完整回归。

| 检查 | 最终结果 |
|---|---|
| 本项新增用例 | 34 passed |
| 本项 + 架构 + HTTP 契约 | 48 passed（34 + 11 + 3） |
| 全项目回归 | 377 passed / 1 skipped / 0 failed |
| Ruff safemeal/tests | PASS |
| mypy safemeal | PASS，293 个源码文件 |
| 新增 4 个 Python 文件格式 | PASS |
| git diff --check | PASS |
| 收藏和批量业务 SQL 预算 | 各 1 条，通过 |
| SQLite 收藏索引计划 | 命中 ix_recipe_reactions_favorites，无临时排序 |
| MySQL 实机 / 线上 OIDC | NOT EXECUTED |
| 用户数据库迁移 | 未执行 |

JUnit：`evaluation_results/backend_feature_05_pytest.xml`；迭代记录：`evaluation_results/backend_feature_05_iterations.json`。

## 8. 测试后的代码与架构审阅

| 文件/层 | 结论 |
|---|---|
| 既有 identity 模块及安全适配器 | 复用注册/登录/轮换/状态检查，无新增身份表或另一套认证服务 |
| interfaces/http/authentication.py | 在现有认证适配中修复 JWKS 复用、字符串身份验证和会话存储身份键，保持 Principal/Actor 边界 |
| contracts/behavior.py | 收藏页、批量输入输出契约；请求体不含可选择主体的身份字段 |
| application/interaction_service.py | 复用服务，负责输入范围、去重顺序与有界分页；不依赖 SQL/Redis/HTTP/Agent |
| ports/reaction_repository.py | 扩展既有行为仓储协议，不暴露连接/Session |
| infrastructure/persistence/reaction_repository.py | 一次聚合/一次 JOIN、条件身份过滤与 SQL 异常映射在适配器；保留原写入语义 |
| interfaces/http/routers/behavior.py | 只映射认证、参数、响应和线程池调用 |
| interfaces/__init__.py | 静态 favorites 路由先于动态 recipe_id 详情注册 |
| 既有组合根 | 继续使用已装配的 InteractionService，不新增后台任务或缓存实例 |
| 新 migration | 独立加/删索引，升级/降级保留行为数据 |
| tests/refactor/test_http_surface.py | 增加 favorites GET / interactions/query POST 断言，原 auth/chat/knowledge/recipes 断言保留 |

11 项自动架构约束通过。Agent 图和工具未修改；MQ、消费幂等、重试队列等第六项工作尚未开始。

## 9. 用户确认

第五项已完成实现、测试和架构审阅。请确认是否开始第六项 P2「行为事件处理」（MQ、重复消费、重试、最终一致性）。确认前不开始第六项。
