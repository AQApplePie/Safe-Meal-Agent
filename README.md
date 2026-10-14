# SafeMeal

面向 Python 后端与 Agent 应用开发的模块化项目，两种入口共享食谱、身份与交互业务。

| 方向 | 入口 | 运行依赖 |
|---|---|---|
| Recipe Platform | `safemeal.platform_main:app` | API + MySQL + Redis；`requirements-platform.txt` |
| Agent | `safemeal.main:app` | 完整模型、检索、会话与 checkpoint；`requirements.txt` |

平台独立启动、演示数据、测试、架构与验收记录见 [后端独立运行](docs/optimization/01_backend_independent_runtime.md)。Agent 设计见 [Agent README](safemeal/agent/README.md)。两部分当前的技术清单见 [技术栈](docs/optimization/00_technology_stacks.md)。

核心后端的类、字段、实例属性、函数和方法均有中文说明；枚举取值逐项解释，SQL 实现类明确标注。
字段注释范围与验证结果见 [字段注释说明](docs/backend_field_comments.md)。
运行 `make comments-check` 可检查注释完整性；发布文件整理与验证结果见
[发布整理记录](docs/release_cleanup.md)。

平台最短启动路径（Docker Desktop 需运行）：

```sh
docker compose --env-file .env.platform.example -f docker-compose.platform.yml up --build -d --wait
```

访问 `http://localhost:8100/docs`。这是本地演示配置；生产配置校验、数据卷与停止命令见上述运行文档。

真实 MySQL 迁移、并发、锁失败与双进程事件恢复验收见 [后端 MySQL 联调](docs/optimization/02_backend_mysql_integration.md)，运行 `make test-mysql` 会创建并清理专用临时容器。

真实 HTTP 压测、缓存冷热对照、SQL 执行计划与索引优化见 [后端性能实验](docs/optimization/03_backend_performance_sql.md)，运行 `make bench-backend` 会生成隔离合成数据并清理临时服务。

运行指标、真实 Redis 故障恢复与死信运维见 [后端运维闭环](docs/optimization/04_backend_operations_recovery.md)。`make test-operations` 验证指标与隔离故障演练；`python -m scripts.outbox_admin status` 查看 SQL outbox，死信只能按 UUID 显式重投。

- [Agent 固定评测集与离线基线（第 6/9 份）](docs/optimization/05_agent_evaluation_baselines.md)
- [Agent 延迟、Token 与成本观测（第 7/9 份）](docs/optimization/06_agent_latency_token_cost.md)
- [Agent 审批界面与恢复流程（第 8/9 份）](docs/optimization/07_agent_approval_resume.md)
- [Agent 检索质量与消融（第 9/9 份）](docs/optimization/08_agent_retrieval_quality_ablation.md)
