# 文档 3/9：传统后端第二项——真实 MySQL 联调与并发验证

日期：2026-10-09。对应实习评估的后端第二条。本项已完成实现、真实服务测试、必要回归与架构审阅；下一项需用户确认。本轮没有迁移、清空或降级用户现有数据库。

## 1. 结果

新增可重复的真实 MySQL/Redis 验收，覆盖迁移往返、并发交互、唯一约束与租户隔离、同事务 outbox、锁冲突、双进程消费、去重、重试和租约恢复。

实际测试发现并修复了三类 SQLite 未能揭示的问题：历史迁移降级时提前删除外键支持索引、outbox 时间字段的 MySQL 小数秒舍入，以及浏览历史在可重复读旧快照与无变化 UPSERT 下的写后读取错误。另补充了仅针对明确锁冲突的有限整事务重试。

最终全量：**432 passed、1 skipped**，其中 **20 项真实 MySQL/Redis 测试全部通过**。不是将原 SQLite 用例改名为 MySQL 测试，也没有把并发正确性当作吞吐压测成果。

## 2. 实际发现与修复

### 2.1 降级删除索引的顺序

真实 MySQL 返回 1553：索引仍被外键依赖，不能先删除。

- `20260710_0002`：先删除 `fk_chat_messages_reply_to_message`，再删除 `uq_chat_messages_reply_to`。
- `20260705_0001`：按子表到父表顺序直接 DROP TABLE，由数据库同时移除该表的索引与外键，避免先逐个删除外键支持索引。

只修正这两份历史迁移的 downgrade，没有改写它们的 upgrade、版本号或迁移链。验证完整 `head → base → head`，目录中 70 条食谱保留；应用表按降级语义删除后重新创建。这不等于任意业务数据都能无损降级。

### 2.2 outbox 时间精度

确定性复现：写入 `2026-10-09 12:00:00.900000`，旧 MySQL `DATETIME(0)` 存成 `12:00:01`。`retry_at` 因而晚于当前 Python 时间，刚创建的事件暂时不可 claim；租约/重试边界也存在舍入偏差。

新增迁移 **`20261009_0013`**，将 `created_at`、`available_at`、`retry_at`、`lease_until`、`completed_at`、`dead_at` 六列改为 MySQL `DATETIME(6)`，仓储 metadata 同步。SQLite 仍使用原 DateTime 行为。

验证：小数秒完整保留、事件立即可 claim、16 并发 claim 仅一人获胜、过期租约可重领且旧 token 无法完成新租约。同时验证 `0012 → 0013` 保留已有事件与字段值。已有被舍入的旧时间不会凭空恢复原始精度；将 0013 降回 0012 会降低小数秒精度。

### 2.3 浏览历史的可重复读快照

24 并发浏览在全量回归中出现 `NoResultFound`，最终映射为数据库操作失败。已增加确定性复现：

1. 第一个事务读取食谱，建立旧 RR 快照，暂停于历史 INSERT 前。
2. 第二个事务插入同一历史行并提交，使用更晚的时间。
3. 第一个事务执行 `GREATEST` UPSERT，因为已有时间更晚，实际不改变行。
4. 普通 SELECT 仍使用旧快照，可能看不到该行。

修复：MySQL 写后读取历史时间使用同一事务内的 `SELECT … FOR UPDATE` 当前读。保留 `GREATEST` 防止时间倒退，不为了读取而给全部浏览请求增加食谱级串行锁。SQLite 路径维持原行为。

确定性复现与 24 并发浏览均已通过，历史事实只有一行，对应 outbox 正常提交。

## 3. 锁失败处理与边界

新增 `infrastructure/persistence/transaction_retry.py`，由点赞/收藏和浏览历史仓储调用。

| 情况 | 行为与实测 |
|---|---|
| MySQL 1205 锁等待超时 | 完整事务退出并回滚后有限重试；释放阻塞锁后成功，仅一个事实/事件提交 |
| MySQL 1213 死锁 | 回滚受害事务并从头重做；两个事务反向锁定食谱制造真实死锁，尝试次数为 1 与 2，最终两个事件而非三个 |
| 重试耗尽 | 仓储保持 `DatabaseUnavailableError`，HTTP 503；两次真实 1205 后没有事实/事件残留，释放锁后客户端重新 PUT 成功 |
| MySQL 2013 连接丢失 | 不自动重放；本轮杀掉自有测试事务连接，仅尝试一次，服务器回滚未提交事件 |
| 非锁错误、未知错误、SQLite 错误 | 不进入 MySQL 锁重试策略，维持原异常处理 |

重试整个事务，而非只重复失败 SQL；因此行为与 outbox 的事务边界不变。事务闭包只包含数据库操作，未把 Redis、模型或其他外部副作用放入重试范围。

配置新增：

| 配置 | 默认 | 范围/含义 |
|---|---|---|
| `DB_LOCK_WAIT_TIMEOUT_SECONDS` | 2 | 1–30 秒；新 MySQL 会话的 `innodb_lock_wait_timeout` |
| `DB_TRANSACTION_MAX_ATTEMPTS` | 3 | 1–5 次；首次也计入次数；作用于上述两个仓储 |

退避带少量抖动；默认两次重试分别等待 5–15 ms、10–30 ms。重试日志只记录错误码与次数。SQL/Redis I/O 与退避仍在原 HTTP 线程池执行，不在异步请求的事件循环中直接 sleep。

锁等待参数约束单次锁等待，不是整个 HTTP 请求的硬超时。连接/COMMIT 响应丢失可能有不确定结果，本轮不自动重试此类错误；连接丢失实验是提交前断连，不宣称穷尽所有 COMMIT 响应丢失窗口。

平台与 Agent API 的 Compose 已传递这两个配置，平台 `.env` 示例也已补齐。组合根真实会话查询确认配置值生效。身份/聊天等其他仓储没有被笼统套用此重试策略，后台 outbox worker 仍依赖其既有持久状态与循环恢复机制。

## 4. 20 项真实服务验收

环境：MySQL **8.0.46**、Redis **7.4.11**，隔离级别 **REPEATABLE-READ**，70 条固定种子食谱。专项引擎将锁等待设为 1 秒以快速、确定性地产生超时；另验证组合根配置的真实会话为 2 秒。

| 分组 | 项数 | 实际结果 |
|---|---:|---|
| 迁移与已有事件升级 | 2 | head/base/head 往返；目录数据保留；0012 到 0013 的已有事件保留 |
| 同用户/不同用户交互 | 3 | 点赞、收藏各 24 并发添加/取消；同用户一行→零行；24 不同用户返回计数 1…24，取消后零 |
| 身份与数据库约束 | 1 | `team/Team`、`alice/Alice` 不混同；重复主键与无效食谱 FK 被 MySQL 拒绝 |
| 行为/outbox 原子回滚 | 3 | 点赞、收藏、浏览在行为与事件 INSERT 后注入异常，二者都回滚 |
| 浏览历史 | 2 | 24 浏览去重与排序；旧 RR 快照 + no-op UPSERT 的确定性回归 |
| 真实锁冲突 | 3 | 1205 成功重试、重试耗尽的真实 HTTP 503、1213 整事务重试 |
| SQL 租约 | 1 | 16 并发抢占唯一获胜者；过期重领、旧 token fencing |
| 双进程消费 | 1 | 两个 spawn 进程、不同 PID/consumer；12 个重复通知不重复累计；崩溃消费者 PEL 被恢复 |
| 重试/死信/恢复 | 1 | 真实榜单租约竞争使刷新失败；重复通知不能绕过退避；两次失败进 SQL 死信；解除竞争并 requeue 后完成 |
| 连接丢失 | 1 | 真实 2013，只有一次尝试，没有自动重放 |
| 小数秒边界 | 1 | `.900000` 原样存储，即时 claim 成功 |
| 组合根配置 | 1 | 实际锁等待值与一次尝试配置生效，释放锁后写入恢复 |

同用户重复 PUT/DELETE 的事实状态幂等；当前每次成功命令仍各有一个 outbox 通知，所以 24 添加 + 24 取消为 48 个事件。不能把它描述为同一业务命令只有一次投递。消费者以 SQL 完成状态去重，并从 SQL 事实重建榜单，不依赖事件次数加分。

双进程消费使用各自 SQL 引擎与连接，未共享进程内锁。验证崩溃 PEL 时只调整自有 Redis pending 消息的 idle 时间，验证 SQL 租约时只调整自有测试事件的租约截止时间，避免等待 30/180 秒；这是受控恢复实验，不是生产运行时长证据。

## 5. 重复运行

Docker Desktop 需运行，使用项目测试环境（Python 3.12 与完整 requirements 已包含 pytest；无需模型密钥）：

```sh
make test-mysql
```

等价命令：

```sh
RUN_MYSQL_INTEGRATION=1 python -m pytest tests/integration/test_mysql_backend.py -q --junitxml=evaluation_results/mysql_integration_pytest.xml
```

包含专项的全量回归：

```sh
RUN_MYSQL_INTEGRATION=1 python -m pytest tests -q --junitxml=evaluation_results/mysql_backend_final_pytest.xml
```

本轮最终使用 `/opt/homebrew/Caskroom/miniconda/base/envs/agent_env/bin/python`，全量运行 24.04 秒；该时间包含测试/容器操作，不作为 API 性能指标。

测试通过 Docker CLI 创建随机命名的 `sm-mysql-it-*`、`sm-redis-it-*` 容器，只绑定本机动态端口；MySQL 使用临时文件系统，Redis 关闭持久化。生成临时密码，不接收外部测试数据库 URL，不使用 `.env` 中的用户数据库。迁移过程临时设置自有 URL 并在结束后恢复环境变量。关闭连接、join/终止自有子进程后移除自有容器，清理结果写入环境报告。

未设置开关时，普通 pytest 会明确跳过这 20 项，不应把跳过结果写成真实服务验证成功。设置开关后 Docker/服务不可用会失败，不以 skip 掩盖。原 `make test-integration` 的 `RUN_TESTCONTAINERS=1` 也可启用这些用例；实现使用 Docker CLI，pytest 的 `testcontainers` marker 用于选择这些临时容器测试，不代表依赖该库完成装配。

## 6. 文件与架构审阅

| 文件/边界 | 审阅结论 |
|---|---|
| `infrastructure/persistence/transaction_retry.py` | SQL 专属策略位于基础设施；重试前退出事务，保留异常映射 |
| `reaction_repository.py`、`history_repository.py` | 仍实现原 ports；修改 SQL/事务行为，没有将 SQL 规则移入 application 或 HTTP |
| `behavior_outbox.py` 与 0013 | metadata 与实际迁移精度一致，保留持久状态与租约语义 |
| 历史 0001/0002 downgrade | 修复外键支持索引依赖；原 upgrade 与版本定位不变 |
| `config/platform.py`、`database.py`、`platform_container.py` | 配置校验→组合根→会话/仓储参数，Agent 继承共享能力 |
| 两份 Compose、`.env.platform.example` | 新参数可传入，Compose 配置校验通过 |
| `tests/integration/test_mysql_backend.py` | 实际 SQL/Redis/多进程；资源只由该 fixture 创建和删除；默认显式 opt-in |
| `Makefile`、根 README | 提供重复测试命令与本报告导航，没有增加新的业务运行依赖 |

HTTP 接口、业务 ports、认证身份、异常响应保持兼容。Ruff 通过，11 个本项 Python 文件格式检查通过；Mypy **302** 个源码文件通过；`git diff --check` 通过；现有架构边界测试包含在全量结果中。

无需增加新的运行依赖。没有新增缓存计数事实源、分布式进程内互斥或 Agent 运行耦合。没有重置或覆盖用户预先存在的其他变更，也未创建提交或清理用户数据卷。

## 7. 证据与结论边界

最终证据：

- `evaluation_results/mysql_backend_final_pytest.xml`：432 通过、1 跳过；可按 `test_mysql_backend` 筛出 20 项专项。
- `evaluation_results/mysql_integration_environment.json`：实测版本、隔离级别、迁移 head、各场景结果、两个消费者 PID 与清理结果。
- `evaluation_results/mysql_timestamp_precision_before.xml`、`mysql_timestamp_precision_before.json`：修复前真实时间舍入证据。
- `evaluation_results/mysql_history_snapshot_before.xml`：修复前确定性旧快照错误。
- `evaluation_results/mysql_integration_initial.xml`、`mysql_integration_iteration_02.xml` 至 `mysql_integration_iteration_05.xml`：保留迭代失败与修复验证，不冒充最终通过报告。

全量的一项跳过仍是需要显式 live API 与 `RUN_DEEPSEEK_E2E=1` 的真实模型 E2E，没有计入通过数。本轮测试容器均已移除，环境报告中的清理结果为 true。

本轮已证明选定真实环境下的事务、并发和恢复行为。多数并发操作在仓储/用例层执行，HTTP 层验证了真实锁冲突后的 503；不是 HTTP 吞吐压测，也不是上线多机 HA 验收。下一项再固定数据/负载、做性能实验和 MySQL 执行计划分析。

对于已有运行数据库，当前待应用 head 为 `20261009_0013`；本轮只在自有测试库执行迁移。部署时使用对应环境的正常迁移流程，不能把本报告的 `downgrade base` 当作生产启动步骤。

## 8. 下一项

下一份为文档 **4/9：传统后端第三项——性能实验与 SQL 分析**，重点是固定数据规模/负载、典型查询执行计划、缓存冷热对照、吞吐与 p50/p95/p99、错误率和资源证据。等待用户确认后开始。
