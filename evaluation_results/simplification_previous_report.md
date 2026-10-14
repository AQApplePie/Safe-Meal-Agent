# SafeMeal 架构减法重构最终报告

## 结论

本轮完成了实际减法重构，不新增 Node、双路由或大型抽象。Outer Understanding 和 Outer Constraint Resolution 成为正式执行链的权威语义入口；Initializer、Planner 和 RecipeService 的边界更清晰。

## 删除了什么

- 文件：未发现可以整文件安全删除且不影响公开模块边界的候选，因此未强行删除文件。
- 函数：`_conversation_from_messages`。
- 参数/配置：两层 `history_messages`、`AGENT_HISTORY_MESSAGES`、`RecipeQuery.candidate_limit`。
- 字段：AgentState 的 `human_approved`、`approval_required`、`safety_gate_blocked`；AgentContext 和 WorkflowState 各自的 `resolved_constraints`。
- 分支：PrepareContext 的二次 Request Understanding、二次上下文源加载兼容分支。
- Planner 代码：删除 candidate scan/limit 计算与跨层传递。

## 删除依据

上述项目均通过源码调用扫描确认：没有独立读取者，或职责已经由正式上游/下游唯一组件承担。详细证据见 `architecture_simplification_audit.md` 与 `state_field_audit.md`。

## 收敛后的决策

- Request Understanding：Outer 节点唯一产生 RequestFrame；其内部保留 NLU 失败时规则 fallback。
- Constraint Resolution：Outer 节点唯一从文本、历史、记忆和 Frame 生成 requirements。
- Initializer：只校验、冻结并初始化执行状态。
- Planner：决定下一行动；确定性策略不再拥有内部候选扫描规模。
- RecipeService：统一管理候选召回规模。
- Observer：结果标准化、证据与任务进度。
- Reflector：完成度和是否继续。
- Safety：Dietary 提供唯一领域规则；Final Safety 控制发布。

## 必要的重复保护

- Observer 安全过滤与 Final Safety 复核保留：前者服务执行推理，后者服务发布控制。
- requirements 与 dietary_constraints 保留：完整语义与冻结硬约束是不同产物。
- ToolResult、Observation、Tool Trace 保留：瞬时结果、标准证据和审计轨迹生命周期不同。
- 菜单计划与菜单进度保留：目标不可变，进度可变，二者共同支持 Resume 与多轮修改。

## 测试结果

| 阶段 | Passed | Failed | Skipped/Not Executed |
|---|---:|---:|---:|
| Baseline | 245 | 0 | 1 skipped |
| Final | 245 | 0 | 1 skipped |
| Ruff | PASS | 0 | 0 |
| Startup import | PASS | 0 | 首次因本地缺 DATABASE_URL 无法执行 |

启动重试使用临时 Docker 等价 URL，仅验证应用装配与 import，没有改写 `.env` 或连接/修改数据库。

## 简化指标

| 指标 | Before | After | 变化 |
|---|---:|---:|---:|
| Python source lines | 23,565 | 23,496 | -69 |
| AgentState fields | 32 | 29 | -3 |
| AgentContext fields | 11 | 10 | -1 |
| WorkflowState fields | 8 | 7 | -1 |
| Initializer lines | 173 | 147 | -26 |
| Planner 目录五个核心文件行数 | 765 | 731 | -34 |
| 重复正式语义入口 | 2 | 1 | -1 |
| Inner constraint text resolution | 1 | 0 | -1 |
| 外部候选扫描参数 | 1 | 0 | -1 |

行数统计使用 `find safemeal -name '*.py' -print0 | xargs -0 wc -l`；字段数通过 AST 对指定类的注解字段计数。

## 遗留问题

- `resolve_agent_intent` 仍保留无 RequestFrame 的独立 Agent fallback。当前 `AgentExecutionService` 的公开低层调用和审批集成测试依赖该能力；本轮强删会扩大契约变更，因此记录为 `DEFERRED_ARCHITECTURE_DEBT`。
- AgentExecutionService 的 response/metadata assembly 仍较长，但各片段分别服务错误降级、菜单持久化、证据、SSE/API 和 Resume；没有足够证据证明可删除，未为了行数拆成新的抽象。
- 本轮没有连接真实外部 LLM/数据库执行破坏性 E2E；完整确定性/Mock 回归通过，应用装配通过。真实基础设施测试需要已启动的 Docker 依赖和有效模型密钥。

