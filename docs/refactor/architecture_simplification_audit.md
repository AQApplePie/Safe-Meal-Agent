# 架构减法审计

## 已处理问题

### SIM-001：Initializer 从 messages 二次恢复历史

- Location: `runtime/orchestration/nodes/initializer/node.py`
- Problem: `_conversation_from_messages` 允许 Inner Runtime 从消息副本重新建立历史，与 Outer Context Builder 竞争。
- Evidence: 生产调用已把 `AgentContext.conversation_history` 传入；该 helper 只有 Initializer 自用。
- Behavioral role: 旧的独立图调用兼容。
- Change: 删除 helper、`history_messages` 参数和 `AGENT_HISTORY_MESSAGES` 配置。
- Risk: 独立构造图的调用方必须遵守 `AgentContext` 输入契约。
- Tests: workflow、agent graph、approval/resume、全量回归。

### SIM-002：PrepareContext 内存在第二个 Request Understanding

- Location: `workflow/nodes/prepare_context.py`
- Problem: 缺少 Frame 时再次运行 `RequestUnderstandingService`，形成第二语义入口。
- Evidence: 正式图固定由 `understand_request → prepare_context`；唯一消费者的单元测试可显式提供 Frame。
- Change: 改为要求 `state["request_frame"]`，同时删除重复加载上下文的兼容分支。
- Risk: 直接单独调用节点必须提供上游契约。
- Tests: Request Understanding、菜单修改、短期引用、完整 workflow。

### SIM-003：无消费者的审批与安全状态

- Location: `contracts/state.py`、Initializer、Approval、Planner constraints。
- Problem: `human_approved`、图内 `approval_required`、`safety_gate_blocked` 只有写入者，没有读取者。
- Evidence: 审批控制由 `interrupt`、`pending_calls` 和 Gateway metadata 完成；安全阻断已经编码在 `route`。
- Change: 删除 3 个 AgentState 字段及其写入。
- Risk: 无；没有动态序列化消费者，审批/恢复测试覆盖实际契约。

### SIM-004：重复的 resolved constraints 状态

- Location: `AgentContext`、`WorkflowState`、`resolve_constraints`。
- Problem: `resolved_constraints` 写入后无读取者；权威数据已包含在 `requirements.resolved`。
- Change: 删除两个字段及两处复制。
- Risk: Gateway 的外部 metadata 仍从 `requirements` 生成，API 不变。

### SIM-005：Planner 拥有检索召回规模

- Location: `planner/strategy.py`、`RecipeQuery`、`RecipeService.recommend`。
- Problem: `candidate_limit` 是内部召回策略，却由 Planner 计算并跨 Tool 边界传递。
- Change: 删除 Tool 参数；原有普通三倍过采样和品类过滤时 200 条扫描公式移到 RecipeService。
- Risk: 召回行为必须完全保持；数量、鱼类/海鲜/素菜测试覆盖。

## 保留或延期

- `resolve_agent_intent` 的无 Frame fallback：保留。`AgentExecutionService` 仍是公开的 `AgentInvoker`，审批和低层集成测试存在独立调用；有 Frame 时它只映射结构化任务，不重复分类。标记 `DEFERRED_ARCHITECTURE_DEBT`，若未来禁止独立 Agent 调用再删除。
- `requirements` 与 `dietary_constraints`：保留。前者是完整用户语义，后者是给 Tool/Observer 使用的冻结硬约束编译结果。
- `tool_results`、`observations`、`tool_trace`：保留。分别对应瞬时执行结果、长期标准证据、审计用 proposed/effective args，生命周期不同。
- Observer 与 Final Safety 的两次检查：保留。前者形成执行证据，后者控制发布，且共同调用 Dietary 规则而不是复制 taxonomy。
- `question`、`messages`、`conversation_history`：保留。分别用于当前任务、LangGraph/Checkpoint 消息以及不含当前问题的 Prompt 历史。


## 本次重新审计（以任务开始时工作区为基线）

已有未提交重构与报告均保留。先前 SIM-001～005 是任务开始时的已有变更，不能计为本次新增成果。真实运行基线：245 passed / 1 skipped；Python 3.12 agent_env；HEAD 74ae66b4f6e23f5c99855c639bd735a304599333。

### SIM-006

- Location: gateway/service.py:process、resume。
- Problem: 首次与恢复各自解释结果；恢复没有 outcome 分类、完成度、菜单持久化或展示顺序。
- Evidence: 原 resume 仅输出 session_id/approved、recipe、evidence/sources；process 含推荐完成度、菜单和 trace。
- Behavioral role: HTTP 返回、发布复核、后续菜单引用、故障分类。
- Recommended change / 实施: 共用 `_build_response`、`_invoke` 和错误分类；删除 resume 的独立组装分支。保留恢复 route 和 approved 外部字段。
- Risk: 恢复结果从默认 ok 改为真实 degraded/error，正确揭示部分证据；不再发布空回答。
- Tests protecting behavior: test_simplification_boundaries 的部分数量恢复、菜单 metadata、timeout、capacity；原 approval/deny 和 Checkpoint 回归。

### SIM-007

- Location: safety/dietary_safety_service.py:resolve_constraints；workflow/nodes/constraints.py；initializer/node.py。
- Problem: history 参数从未被读取；Frame 硬约束合并位于 Outer 节点，独立 process 无 requirements 时 Inner 用空契约。
- Evidence: service 函数 AST 中没有 history Load；正式图仅 Gateway 调用；独立调用在现有测试中真实存在。
- Behavioral role: 保留当前文本、类型化记忆、可信 Frame、显式 carryover；不重新挖历史。
- Recommended change / 实施: 删除 history 参数及全部实参；Frame 合并进入已有 service；Workflow 和独立 Gateway 调用同一个 service。已有 requirements 不再解析。Initializer 缺失输入明确拒绝。
- Risk: 直接绕过 Gateway 调用内图需要已解析 requirements；这是一条明确内部输入契约。process() 无 context 仍可使用，不损失 allergy fallback。
- Tests protecting behavior: standalone allergy、resolved_input 不重解释、structured frame allergy；history scope、negation、dietary、workflow 测试。原历史测试的数据迁入 AgentContext.conversation_history，断言未删除。

### SIM-008

- Location: aggregation/responder.py；reflector/assessment.py。
- Problem: 相同 recommendation_count/fulfilled_count 扫描两份；assessment 先排除上下文工具，再只接收 generate_recipe/multi_route_retrieval 白名单，前者不可能影响后者。
- Evidence: 两段相同的逆序筛选条件和整数转换；上下文工具集合与白名单互斥。
- Behavioral role: 完成度由工具确定性证据定义，Respond 仅显示部分结果。
- Recommended change / 实施: Respond 使用已有 recommendation_completion；删除无效果的预过滤集合/列表。
- Risk: 不把 has_data 当作 completed；返回三元组包含明确 complete。
- Tests protecting behavior: test_partial_count_survives_checkpoint_resume_and_final_safety、原 count/menu/safety 测试。

### SIM-009

- Location: initializer/node.py、planner/node.py。
- Problem: Initializer 单消费者 Observation 包装无独立逻辑；Planner 两分支重复预算快照与状态写回。
- Evidence: `_context_observations` 仅 Initializer 引用；两条 Planner 路径同写 intent/context/observations。
- Behavioral role: JSON → typed Observation 是校验边界，仍保留；预算在模型返回后取快照。
- Recommended change / 实施: 删除包装；共享预算构造与最终状态写回。
- Risk: 不改变确定性策略优先级、工具预算闸门或模型调用条件。
- Tests protecting behavior: 原 Planner/budget/graph/menu/Classifier 回归。

### SIM-010

- Location: workflow/review_reply.py、context/history.py、workflow/context/builder.py、understanding/request_understanding.py。
- Problem: 无使用者的 render_review_reply；history/active_menu 单字段包装无正式消费者；JSON 包装只转调同函数；同一函数两份中文数量映射。
- Evidence: 全 safemeal/tests rg、AST 属性/字符串/export/decorator 扫描；history-only wrapper 唯一使用是所有权测试；Builder 正式调用 load_context_before_turn。三个 JSON 转换使用者行为相同。
- Behavioral role: 发布文案、事务快照、纯转换、中文数量。
- Recommended change / 实施: 删除 4 个包装（含有 test-only 消费者的 history wrapper），改所有权测试调用实际快照入口；数量复用当前函数 number_values。
- Risk: 内部调用名删除，不改变 HTTP、SSE 或数据库契约。
- Tests protecting behavior: 全量回归、stored_turns 所有权测试、推荐四道鱼/两荤两素/菜单引用。

## 全项目死代码扫描边界

`evaluation_results/simplification_symbol_candidates.json` 是 Python AST 初筛，不是死代码定论。Pydantic validators、HTTP decorator callbacks、Protocol 实现和 exports 属于真实动态消费者。逐一检查重点链路候选后，只删除本次有明确证据的 5 个包装函数。未证明无使用者的公共端口、配置、Checkpointer 类保持 UNCERTAIN。

CheckpointSerializer 的历史模块映射保留：旧 JSON/msgpack 保存的是模块路径，测试真实构造旧路径并验证恢复，不能因为没有 import 就删兼容层。Provider 的 collect/collect_selected 参数属于可替换扩展端口，不能按某一实现没读取就删。

## DEFERRED_ARCHITECTURE_DEBT

- resolve_agent_intent 原文兼容分支：独立 process 和模糊问题 classifier 测试真实依赖；可信 Canonical Frame 在 fallback 前直接映射；保持其能力，需要统一独立语义入口时才整体变更契约。
- 外部 metadata 的 reflect 重复摘要：Python 之外的消费者无法全部证明，保留。
- 类型债务的 31 项错误已在后续有限修复中清零；121 项既有格式债务保留，不通过大量无关改动重写全库。最终报告不标记全量验收 COMPLETE。

