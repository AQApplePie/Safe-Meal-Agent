# SafeMeal 物理架构重构日志

==================================================
PHASE 0
==================================================

Timestamp: 2026-10-06 Asia/Shanghai

Git HEAD: `26cc05c463d30f3fecbc6224e3ffd642fbe77e1e`

Goal: 记录物理迁移前的代码状态和回归基线。

Files inspected:

- `safemeal/`
- `tests/refactor/`
- `tests/evaluation/`
- `tests/e2e/`

Files moved: 无。

Files modified: 仅新增本重构日志。

Imports changed: 无。

Compatibility exports added: 无。

Dependency changes: 无。

Tests before: `PYTHONPATH=. conda run -n agent_env python -m pytest -q`

Tests after: `243 passed, 1 skipped in 3.46s`

PASS

Observed problems:

- 基线中存在前序任务产生的未跟踪实现和评估文件，本次必须保留并纳入迁移。
- Agent、共享业务服务和应用契约仍集中在 `safemeal/application/` 下。

Root cause: 当前目录按技术类型和历史演进组织，模块所有权没有物理体现。

Resolution: 进入 Phase 1，只做职责清单和目标依赖设计。

Remaining risks: 大量内部 import 依赖旧路径；迁移必须逐阶段运行测试。

==================================================
PHASE 1
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 识别真实职责并确定目标依赖方向。
Files inspected: application、agent、workflow、chat、recipe、dietary、identity、knowledge、tool、composition、interfaces、infrastructure。
Files moved: 无。
Files modified: current_module_inventory.md、target_architecture.md。
Imports changed: 无。
Compatibility exports added: 无。
Dependency changes: 明确 modules 不得依赖 agent、LangGraph 或 infrastructure。
Tests before: Phase 0 基线。
Tests after: 文档阶段未重复运行。
PASS
Observed problems: RequestFrame 和聊天目录实际被多个职责共同使用。
Root cause: 历史目录按技术类型增长。
Resolution: 将共享语义与 Agent 专用协调分别规划到 shared 和 agent。
Remaining risks: 批量移动可能暴露隐含反向依赖。

==================================================
PHASE 2
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 建立 Agent 物理边界并保留两层 Graph。
Files inspected: application/agent、application/workflow、application/service/chat。
Files moved: Agent runtime、gateway、workflow、contracts、understanding、context、safety。
Files modified: 全部关联 import 和测试 import。
Imports changed: safemeal.application.agent/workflow/chat → safemeal.agent.*。
Compatibility exports added: 无。
Dependency changes: Outer Workflow 与 Inner Runtime 分离；Agent 专用安全服务归入 agent/safety。
Tests before: 243 passed，1 skipped。
Tests after: tests/refactor 166 passed。
PASS
Observed problems: 共享 RequestFrame 被 Recipe/Dietary 使用。
Root cause: 通用语义契约原先位于 Agent Workflow contract。
Resolution: 迁入 shared/contracts，消除 modules → agent。
Remaining risks: 继续验证业务模块迁移后的装配路径。

==================================================
PHASE 3
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 建立 Recipe 业务模块。
Files inspected: recipes contracts/services/ports、repository/provider adapters。
Files moved: Recipe contracts、application services 和 ports → modules/recipe。
Files modified: import、RecipeService 模型类型依赖。
Imports changed: Recipe 调用统一指向 modules/recipe。
Compatibility exports added: 无。
Dependency changes: 新增最小 RecipeGenerator port，移除 Recipe → AgentModelGateway 类型耦合。
Tests before: 无单独阶段失败。
Tests after: tests/refactor 包含 recipe 搜索、详情和菜单回归并通过。
PASS
Observed problems: menu coverage/output 不是 Recipe CRUD。
Root cause: 旧目录按数据对象而非职责归类。
Resolution: 两者归入 agent/runtime。
Remaining risks: 无行为风险；仅协议类型收窄。

==================================================
PHASE 4
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 分离共享 Dietary 规则与 Agent 发布安全。
Files inspected: dietary contracts/services、constraint tools、workflow safety。
Files moved: 通用规则 → modules/dietary；AgentContext/Observation 适配 → agent/safety。
Files modified: import 和 Tool adapter。
Imports changed: 共享调用指向 modules/dietary，Agent 发布调用指向 agent/safety。
Compatibility exports added: 无。
Dependency changes: modules/dietary → agent 为 0。
Tests before: 无单独阶段失败。
Tests after: evaluation 74 passed。
PASS
Observed problems: DietarySafetyService 同时读取领域契约和 Agent 状态。
Root cause: 共享规则与编排适配原先同目录。
Resolution: 按依赖方向拆分物理所有权，不改算法。
Remaining risks: 无。

==================================================
PHASE 5
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 整理 Identity、Knowledge 与 Conversation。
Files inspected: auth、upload、knowledge、memory、chat persistence。
Files moved: 对应 contracts/application/ports → modules/identity、knowledge、conversation。
Files modified: HTTP、infrastructure 和 composition imports。
Imports changed: 所有业务入口指向新模块路径。
Compatibility exports added: 无。
Dependency changes: 技术实现继续位于 infrastructure。
Tests before: 无单独阶段失败。
Tests after: HTTP、身份、知识与会话测试包含在 240 项最终回归中。
PASS
Observed problems: ChatTurnService 直接调用 Agent Workflow。
Root cause: 它是接口与 Agent 的协调入口，不是纯会话业务。
Resolution: 归入 agent/gateway。
Remaining risks: 外部服务集成受本地依赖健康状态影响。

==================================================
PHASE 6
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: Tool 体系物理收敛。
Files inspected: application/agent/tools、application/tool、application/ports/tools、infrastructure/tools。
Files moved: registry/runtime/policy、contracts、ports、adapters → agent/runtime/tools。
Files modified: Tool import 与 registry 装配。
Imports changed: Tool 只调用 Module Application Service。
Compatibility exports added: 无。
Dependency changes: Tool adapter 不直接依赖 infrastructure/config。
Tests before: 无单独阶段失败。
Tests after: Tool contract 与执行测试通过。
PASS
Observed problems: infrastructure/tools 只剩空入口和旧缓存。
Root cause: 历史 Tool 迁移残留。
Resolution: 删除空目录，不创建替代假实现。
Remaining risks: 无。

==================================================
PHASE 7
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 建立唯一 Composition Root。
Files inspected: application_container、factories、operations、main、HTTP dependencies。
Files moved: application/service/composition → bootstrap/composition。
Files modified: main、HTTP middleware/router 和全部 factory imports。
Imports changed: 具体 infrastructure 由 bootstrap 装配。
Compatibility exports added: 无。
Dependency changes: modules 不直接导入具体 infrastructure。
Tests before: tests/refactor 166 passed。
Tests after: 应用成功构造，标题 SafeMeal Agent，34 条路由。
PASS
Observed problems: 首次启动检查缺少 DATABASE_URL。
Root cause: 本地环境变量未设置，与重构无关。
Resolution: 使用等价 MySQL URL 完成无连接的应用构造检查。
Remaining risks: 真实容器依赖未在本阶段启动。

==================================================
PHASE 8
==================================================

Timestamp: 2026-10-06T14:57:55+08:00
Git HEAD: 26cc05c463d30f3fecbc6224e3ffd642fbe77e1e
Goal: 全量回归、静态检查和旧路径清理。
Files inspected: safemeal、tests、scripts、架构文档。
Files moved: 无新增移动。
Files modified: architecture test、迁移映射、最终架构树和最终报告。
Imports changed: 可执行代码不存在旧 application import。
Compatibility exports added: 无。
Dependency changes: modules → agent/LangGraph/infrastructure 均为 0。
Tests before: baseline 243 passed，1 skipped。
Tests after: 240 passed，1 skipped；Ruff PASS；startup PASS。
PASS
Observed problems: 旧架构测试断言 modules 不得存在。
Root cause: 测试固化了迁移前物理结构。
Resolution: 替换为新依赖方向、双 Graph、Tool adapter 和启动边界断言。
Remaining risks: checkpoint serializer 保留历史模块名字符串以兼容已持久化数据。
