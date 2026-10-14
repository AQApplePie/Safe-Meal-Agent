# 文档 5/9：传统后端第四项——最小指标与故障恢复闭环

日期：2026-10-09。完成实现、专项测试、全量回归与架构审阅。传统后端前四项至此完成；下一项为 Agent 第一项“固定评测集与基线对照”，需用户确认。本轮没有操作用户现有数据库、Redis 或运行中的应用。

## 1. 结果

新增两个入口共享的受保护 `/metrics`、HTTP 延迟/状态指标、缓存来源与异常指标、worker 结果指标和 SQL outbox 状态采集；新增显式死信恢复 CLI 与四条告警规则示例。限流 Redis 失效时明确返回 503，保持拒绝放行；过期 SQL 租约未能提交完成状态时，不再错误增加“已完成”指标。

**12 项专项全部通过；全量 464 passed、2 skipped。** 原 20 项真实 MySQL 联调仍全部通过。Ruff、15 个本轮 Python 文件格式、Mypy（305 源文件）、两套 Compose 配置和 diff 检查通过。最小后端 Docker 镜像构建成功，验证指标路由、运维 CLI、UID 10001 与无 Agent SDK 导入。

真实故障演练证明：停止自有 Redis 后，MySQL 保留 3 个待处理事件；恢复 Redis 后，原后台 worker 自动投递/消费，SQL 显示 3 个完成事件，待处理归零，热门榜单分数为 2（点赞＋收藏），没有按 3 次通知加分。另验证实际租约冲突导致死信、CLI 重投，以及真实 MySQL 停止时的采集失败。

## 2. 指标、含义与边界

| 指标 | 类型/标签 | 含义 |
|---|---|---|
| `safemeal_http_requests_total` | counter；method、route、status | 完成的 HTTP 请求；route 使用匹配到的模板，未知/提前拒绝请求归 `__unmatched__`；方法不在常见集合时归 OTHER |
| `safemeal_http_request_duration_seconds` | histogram；同上 | 请求完整 ASGI 处理时长，桶从 5 ms 到 60 s，含 +Inf、sum、count；流式响应统计完整流结束时长，不是首 token 或模型时长 |
| `safemeal_recipe_cache_requests_total` | counter；kind=list/detail、source=l1/redis/database | 缓存装饰器每次逻辑读取只归一个最终来源；database 表示回源尝试，包含回源失败。没有配置该装饰器时不产生这组计数 |
| `safemeal_recipe_cache_errors_total` | counter；operation 固定集合 | Redis 读/写、缓存解码失败的操作次数；锁内二次检查可能使一次请求产生两个读失败，不是 HTTP 错误率 |
| `safemeal_behavior_events_total` | counter；outcome 固定集合 | published、completed、refresh_failed、ignored、invalid、cycle_failed、cycle_success。发布不等于消费完成；重复/未知/租约冲突通知归 ignored |
| `safemeal_behavior_last_success_unixtime` | gauge | 本进程最近一次成功 worker 周期时间；成功空轮询也更新，不代表每个事件都成功 |
| `safemeal_outbox_pending` | gauge | SQL 中未完成且未进入死信的事件，含等待重试与租约中的事件 |
| `safemeal_outbox_leased` | gauge | pending 中当前有有效租约的事件 |
| `safemeal_outbox_oldest_pending_age_seconds` | gauge | 最老 pending 创建时间距当前的秒数；空队列为 0；不包含死信 |
| `safemeal_outbox_dead` / `completed` | gauge | SQL 死信与已完成行数；是当前保留行数，不是永不下降的历史累计 counter |
| `safemeal_outbox_failed_attempts` | gauge | SQL 行中 attempts 的总和；显式重投或数据清理可使其下降，因此不能当作 counter 做 rate |
| `safemeal_outbox_enabled` / `collector_up` | gauge | 是否配置行为 outbox，以及最近一次 SQL 采集是否成功；未配置时均为 0 |
| `safemeal_outbox_collected_unixtime` | gauge | 最近一次实际 SQL 采集尝试时间；可判断缓存快照的新鲜度 |

HTTP、缓存、worker counter 属于单进程，重启归零。SQL gauges 来自持久事实；多副本共享数据库时不要直接相加重复的 pending/dead 值，统一数据库视图可取 max；HTTP 请求量则可按实例汇总。没有用户、租户、原始请求路径、食谱 ID、查询内容、JWT、事件 UUID 等动态标签。

导出 Prometheus text 0.0.4；真实故障/恢复的两份文本通过已安装 Prometheus 客户端解析器验证。生产运行没有新增 prometheus_client、监控 SDK 或外部服务依赖；解析器只用于本次验证。

## 3. 开关、保护与采集开销

| 配置 | 默认 | 行为 |
|---|---|---|
| `METRICS_ENABLED` | false | 显式启用后注册 `/metrics` 与 HTTP 中间件；关闭时没有该路由，也不注入缓存/worker observer |
| `METRICS_TOKEN` | None | 配置后仅接受 `Authorization: Bearer <token>`，长度至少 32；普通用户 JWT 不能访问；生产启用指标必须配置此 token |
| `METRICS_OUTBOX_SCRAPE_SECONDS` | 5 | 1–60 秒；SQL 快照最小采集间隔，单进程锁合并并发 scrape |

两个 `.env` 示例开启本地演示指标并提供明确的开发 token；实际用户 `.env` 未修改。两套 Compose 已映射三个配置。无 token 的开放模式仅适用于显式启用的开发/测试配置；生产配置校验拒绝这种组合。token 的模型 repr 不展示它，校验使用常量时间字节比较；指标响应 `Cache-Control: no-store`。

`/metrics` 不受 Redis 限流中间件约束，但仍受独立 token 保护，避免 Redis 故障阻断观察；scrape 自身不计入 HTTP 指标。健康检查仍按原契约执行。

SQL 快照由后台线程中的单条聚合查询产生，最多每个配置周期重新采一次。SQL 异常后输出 `collector_up=0`，移除旧 pending/dead 等状态，不伪报健康空队列；快照在周期内可能滞后最多约 5 秒。没有新增 SQL 查询硬超时：极慢查询可能使 scrape 超时，应结合采集端自身的 `up` 与时间戳监测。队列表随已完成历史增长，聚合开销需持续观察；本轮未引入自动删除事件或历史保留策略，也未宣称指标没有性能开销。

## 4. 真实 Redis 故障与自动恢复

测试调用真实平台工厂、生产 lifespan、真实注册/JWT 鉴权、SQL 事务和后台 workers。HTTP 由 ASGI TestClient 驱动；MySQL/Redis 为真实 TCP 服务，不是 mock。API 网络吞吐另见上一份性能实验，本项没有把 TestClient 验收当成 TCP 压测。

| 阶段 | 实际操作/接口 | SQL 事实/事件 | 指标与结果 |
|---|---|---|---|
| 健康 | 注册真实用户，读取食谱，readyz=200 | 0 交互，0 pending | 指标须运维 token；匿名和普通 JWT 都是 401 |
| Redis 停止 | Docker stop 自有 Redis；livez=200，readyz=503；等 L1 到期后读食谱；点赞、收藏、浏览各一次 | 2 条交互事实，3 pending，0 completed | 读取真实回退 SQL；缓存读异常、worker cycle_failed 可见；SQL collector_up=1，pending=3 |
| Redis 恢复 | Docker start 同一自有 Redis；保持连接地址；等待原 worker 自动恢复 | 事实仍 2；pending=0、completed=3 | readyz=200；completed counter=3；热门榜单分数=2；关闭应用后 worker task 结束 |

没有人工修改 available_at、retry_at 或租约截止时间，没有手工重建这 3 个事件，也没有替换 consumer 来冒充恢复。Redis 测试关闭持久化，重启后 stream/group 重建，SQL 仍是恢复依据。

**限流边界：该恢复演练没有配置 Redis 限流。** 它证明缓存/事件 Redis 故障时这些链路可以降级并保留新事件；不能推广为默认 Compose 的所有接口继续可用。若限流与缓存/事件共用故障 Redis，默认限流策略保持 fail-closed：受限业务接口返回明确 503 与 Retry-After=1，业务 handler 不执行，因此故障期间被拒绝的写入不会新增事件；故障前已提交的 SQL 事件仍保留。`/metrics`、livez、readyz 不受此限流拦截，便于观察和恢复。即使直连业务可降级，readyz 仍严格检查已配置 Redis，服务编排可能将该实例摘流。

首轮恢复验收失败已保留。独立探针确认 Docker 的自动分配映射 `127.0.0.1::6379` 在 stop/start 后从 58778 变成 58780，worker 仍连接旧端口。修正只作用于需要重启的运维测试 fixture：用操作系统选择的空闲回环端口建立固定映射，并断言重启后相同；原一般 MySQL/性能测试保持其既有策略。没有把测试环境问题错误归因于生产消费算法。

## 5. 死信、租约与 MySQL 故障

另一个真实 MySQL/Redis 用例持有榜单租约，使 refresh_tenant 返回失败；最大尝试为 1，SQL 事件进入死信：dead=1、failed_attempts=1。释放竞争租约后，通过新的 CLI 显式重投，同一个事件完成，dead=0、completed=1；再次重投已完成事件返回 false/退出码 2，不能重复累计。显式重投按已有业务规则将 attempts 清零，所以该 gauge 随之降低。

`SqlBehaviorOutbox.finish` 现在返回实际更新是否成功。worker 只在有效租约下成功更新后记录 completed/refresh_failed；过期 token 的 UPDATE 未生效则归 ignored。原租约 fencing、事务、backoff 和去重机制保留，全量真实锁竞争/过期租约用例通过。

MySQL 故障另以 Docker stop 自有测试 MySQL 验证：之前成功的 SQL gauges 不再沿用，collector_up=0、pending 等字段缺席。此用例不是“数据库故障时仍能写入”证明；没有可用 SQL 事务就不能承诺行为持久化。

## 6. 操作闭环

新增 [outbox_admin.py](../../scripts/outbox_admin.py)，使用运行环境或显式 `SAFEMEAL_ENV_FILE` 配置，不接受命令行数据库密码，不打印原始数据库异常或用户身份。

- `status`：只读聚合状态，成功退出 0。
- `requeue <canonical-event-uuid>`：只恢复一个未完成的 SQL 死信；成功 0，不满足条件（包括已完成/未知/非死信）为 2；非法参数由 argparse 拒绝。
- 配置/数据库等操作异常：输出通用 operation_failed，退出 3；不输出连接串。先查环境、网络和服务状态，再按需要排查。

最小 Dockerfile 已单独复制此 CLI，完整 Agent 镜像原本包含 scripts。实际部署需重新构建，本文没有替用户启动或重启现有环境。

```sh
# 部署/升级本地演示，使用示例配置：
docker compose --env-file .env.platform.example -f docker-compose.platform.yml up --build -d --wait
# 已启动 api 容器里读取聚合状态：
docker compose --env-file .env.platform.example -f docker-compose.platform.yml exec api python -m scripts.outbox_admin status
# 排查死信原因并恢复依赖后，再显式恢复目标事件：
docker compose --env-file .env.platform.example -f docker-compose.platform.yml exec api python -m scripts.outbox_admin requeue <canonical-event-uuid>
```

上述 event UUID 需由有权限的运维 SQL 查询获得，例如只选 event_id、attempts、last_error、dead_at；没有新增公开管理路由或批量强制重放功能。不要因 pending 大就盲目 requeue，pending/leased 与 dead 是不同状态。

观察指标（本地示例 token；实际以启动配置为准）：

```sh
curl -fsS -H 'Authorization: Bearer development-metrics-token-change-me' http://localhost:8100/metrics
```

建议检测与恢复顺序：先查看 livez/readyz；确认 SQL collector_up 和快照时间；观察 pending 最老年龄、dead、worker 周期失败与 Redis 状态；恢复故障依赖；等待 worker 自动消化 pending；若有 dead，先定位 last_error/竞争/配置原因，再按 UUID 显式重投；最后确认 pending 年龄下降、completed 上升、榜单与 SQL 事实一致。不要以 HTTP 写成功就推断榜单已经更新。

[告警规则示例](../../ops/prometheus_rules.yml) 包含 HTTP 5xx 比例、SQL collector 失效、pending 超龄、死信存在。阈值为示例（5xx 5%、超龄 60 秒等），需要结合实际服务调整；只验证 YAML 语法，没有执行 promtool 的 PromQL 检查，没有部署 Prometheus/Alertmanager，也没有配置通知渠道或声称演练触发了真实告警。

监控查询可从请求 counter 按 status 计算 5xx/4xx 比例；用 histogram_quantile(0.95, sum by(le,route)(rate(safemeal_http_request_duration_seconds_bucket[5m]))) 观察路由 p95；用缓存来源 l1+redis 除以全部来源观察缓存命中比例。counter 用 rate 并允许进程重启；SQL gauges 看当前值与时间戳。低请求量时分位/比例不稳定，不用零样本推断稳定性。

## 7. 验证与架构审阅

| 验证 | 本次结果 |
|---|---|
| 指标线程安全与 histogram | 并发计数/桶边界正确，epoch 时间戳精度回归通过 |
| HTTP 状态与标签 | 200、404、503、500 正确；20 个随机未知路径合并；已匹配路径用模板 |
| 访问控制 | 匿名/错误 token/普通 JWT 拒绝；正确 token 可读；关闭路由/生产 token 校验通过 |
| 缓存 | 回源、L1、Redis 逻辑请求各计一次；坏缓存可回源；observer 异常不改变返回值 |
| SQL 状态/采集 | pending 年龄、租约、死信、重投变化；并发 scrape 只采一次；失败移除旧 gauges |
| 限流故障/租约完成 | 限流不可用为 503 且不运行 handler；过期 finish 不报完成 |
| 真实服务三项 | Redis stop/start 自动恢复；真实死信 CLI 重投；真实 MySQL stop 采集失败 |
| 最小交付 | 镜像构建、无网络 import 验证、UID 10001、CLI 非法 UUID 在连接数据库前拒绝 |
| 最终回归 | 464 passed、2 skipped；跳过 opt-in 性能专项（上一项单独通过）及需外部模型凭据的 DeepSeek E2E |

架构结论：指标实现位于 infrastructure operations；HTTP 适配依赖共享 HttpMetricsSink 契约并由 bootstrap 装配；SQL 聚合位于 persistence。业务服务/领域规则/Agent 决策未引入监控 SDK，缓存与 worker 使用可选 observer，不改变请求与事件的副作用边界。两入口沿用共享 configure_http 与 PlatformContainer，避免重复监控实现。指标不会记录原始身份或通过旁路改变计分、租约、重试。

本轮不新增数据库迁移，head 保持 0014；没有删除旧文档、有效测试与验收证据，没有自动合并/提交 Git，没有修改实际用户配置或发出外部通知。

## 8. 复现与证据

```sh
make test-operations
# 与完整项目回归分开：
RUN_MYSQL_INTEGRATION=1 PYTHONPATH=. python -m pytest -q --junitxml=evaluation_results/backend_operations_final_regression.xml
```

专项只启用自有临时基础设施，不接受外部 DATABASE_URL。fixture finally 关闭连接并删除自有 MySQL/Redis；实际故障服务、端口探针与无网络镜像验证容器全部清理；构建的 ops-verify 镜像保留可复查。

- [专项 XML](../../evaluation_results/backend_operations_pytest.xml)：12 passed。
- [全量 XML](../../evaluation_results/backend_operations_final_regression.xml)：464 passed、2 skipped。
- [真实 Redis 故障/恢复](../../evaluation_results/backend_operations_fault_drill.json)：三阶段 SQL、真实指标文本、worker 关闭。
- [死信恢复](../../evaluation_results/backend_operations_dead_letter.json)：真实租约导致失败、CLI 重投、完成事件拒绝重放。
- [MySQL 故障](../../evaluation_results/backend_operations_mysql_failure.json)：成功→采集失败，旧 gauges 缺席。
- [环境与清理](../../evaluation_results/backend_operations_environment.json)：MySQL 8.0.46、Redis 7.4.11、迁移 head 与容器清理。
- [最小镜像](../../evaluation_results/backend_operations_minimal_image.json)：独立运行检查。
- [文本/规则校验](../../evaluation_results/backend_operations_exposition_validation.json)：Prometheus 文本解析与 YAML 范围。
- [源码与检查](../../evaluation_results/backend_operations_validation.json)：最终哈希、检查、架构审阅。

首轮失败留在 backend_operations_initial.xml / backend_operations_initial_fault_drill.json；端口诊断在 backend_operations_port_probe.json，最终结论以上述成功记录为准。

下一项待确认：Agent 第一项“固定评测集与基线对照”（第 6/9 份文档）。
