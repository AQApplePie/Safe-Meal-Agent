# SafeMeal 真实执行链审计

审计基线：`74ae66b4f6e23f5c99855c639bd735a304599333` 加任务开始时工作区；审计日期：2026-10-08。

## 调用链

| 阶段 | 实际入口 | 读取 | 写入/输出 | 业务判断与外部依赖 | 下游消费者 |
|---|---|---|---|---|---|
| HTTP | `interfaces/http/routers/chat.py:create_chat_turn` | `ChatRequest`、认证主体 | 绑定 `user_id` 的请求 | 仅协议、鉴权与异常映射 | `ChatTurnService.handle` |
| 单轮协调 | `agent/gateway/chat_turn_service.py:handle` | 用户、会话、消息 | 用户消息和最终 Agent 回复 | 调用 `ChatTurnPersistence`，不解释语义 | `ChatWorkflow.run`、HTTP |
| 请求理解 | `workflow/nodes/understand_request.py:UnderstandRequestNode` | 当前消息、最近历史 | `RequestFrame`、预加载历史、活动菜单 | NLU gateway；失败时唯一规则 fallback | `PrepareContextNode` |
| 上下文装配 | `workflow/nodes/prepare_context.py:PrepareContextNode` | `RequestFrame`、预加载历史、活动菜单 | `AgentContext`、补全后的 `RequestFrame` | 解析结构化菜单引用和菜单分类替换；加载记忆 | Constraint Resolver、Inner Agent |
| 约束解析 | `workflow/nodes/constraints.py:resolve_constraints` | 当前消息、历史、Frame、记忆 | `DietaryRequirements`、编译后的硬约束 | 唯一的对话级约束解析；Frame 硬约束合并 | Initializer、Tool Policy、Final Safety |
| Agent 网关 | `agent/gateway/service.py:AgentExecutionService.process` | 消息、会话 ID、完整 `AgentContext` | LangGraph 输入；规范化响应 metadata | 并发、超时、预算作用域、危险请求防线 | Inner LangGraph、Outer Workflow |
| Initializer | `runtime/.../initializer/node.py:initialize` | messages、可信 `AgentContext` | 执行状态、初始 Observation、菜单计划 | 不再解析自然语言约束；只校验和装配 | Planner |
| Planner | `runtime/.../planner/node.py:planner` | Frame、意图、Observation、执行状态 | 下一批 `ToolCall` 或直接终止行动 | 确定性行动由 `strategy.py` 构造；动态任务用模型 | Approval/Executor |
| 行动闸门 | `runtime/orchestration/action_policy.py:validate_tool_actions` | ToolCall、工具规格、预算、调用历史 | 合法且未重复的有界调用 | 工具存在性、Tool/Model Budget、重复调用 | Planner、Reflector |
| Executor | `runtime/.../executor/node.py:execute_tools` | pending calls、可信约束 | `ToolResult`、调用计数、trace | Tool Policy 注入不可削弱的约束；执行注册工具 | Observer |
| Observer | `runtime/.../observer/node.py:observe` | ToolResult、ToolCall、旧 Observation | 标准 Observation、菜单进度 | 结果解释、证据融合、安全过滤视图 | Reflector、Responder |
| Reflector | `runtime/.../reflector/node.py:reflect` | Observation、菜单进度、预算 | 完成/继续/重规划 | 使用共享完成度规则与统一行动闸门 | Planner/Executor/Responder |
| Respond | `runtime/aggregation/responder.py:respond` | Observation、Frame、完成状态 | AIMessage、sources、router | 只基于证据渲染或调用回答模型 | AgentExecutionService |
| Final Safety | `workflow/nodes/safety.py:check_final_safety` | requirements、发布草稿、evidence | 可发布响应 | 调用 Dietary 权威规则复核，不重新抽取约束 | SaveMemory、HTTP |
| 持久化 | `ChatTurnPersistence.save_agent_response` | 发布后的响应和 metadata | 数据库消息 | 只持久化，不参与 Agent 决策 | 后续历史与用户 |

## 结论

- `RequestFrame` 的权威生产者是 Outer Understanding。`PrepareContextNode` 原先为独立节点测试保留的第二次规则理解已删除。
- `DietaryRequirements` 的权威生产者是 Outer Constraint Resolution。Initializer 只接受已解析结构化输入；缺失时拒绝执行。独立 Gateway 缺少 requirements 时使用同一个 DietarySafetyService，不从历史文本再挖约束。
- Observer 更新证据和进度；Reflector 判断是否继续；Final Safety 判断能否发布。三者检查相同事实但承担不同生命周期，不能合并成一次检查。
- Checkpoint 必须保留 pending calls、调用计数、预算、菜单进度和可信上下文；这些不是普通重复 DTO。


## 本次调用链边界补充

- `ApplicationContainer.get_agent_execution_service` 装配原有 inner graph、Checkpointer、budget、工具注册表；不新增节点。
- 常规 HTTP：create_chat_turn → ChatTurnService.handle → persistence.start_turn（已授权用户消息）→ ChatWorkflow.run → UnderstandRequestNode → PrepareContextNode → resolve_constraints → InvokeAgentNode → AgentExecutionService.process → `_invoke` → 内图 initialize/planner/approval/execute/observe/reflect/respond → `_build_response` → check_final_safety → save_memory → persistence.save_agent_response。
- SSE：chat stream 路由 → stream_answer_events → 相同 handle 用例；suppress_answer_stream 阻止草稿流出，reviewed/persisted answer 才进入完成事件；执行异常、首包超时、断连取消机制保留。
- 审批恢复：resume 路由先做会话权限校验 → ChatWorkflow.resume → ResumeAgentNode → AgentExecutionService.resume → `_invoke(Command(resume))` → Checkpoint 从 approval 恢复 → `_build_response` → Outer resolve_constraints（复用 checkpoint requirements）→ Final Safety。恢复路径不再次调用 Understand/Initializer，不解析新的空请求。
- 独立 Agent：process(..., context=None 或 requirements=None) 在 Gateway 使用既有 DietarySafetyService 解析一次；已解析输入直接传入内图。Planner 无可信 Frame 时仍保留 IntentClassifier/规则兼容，其触发条件见 intent_from_request_frame。
- RequestUnderstandingService 提取目标、数量、菜单配额、上下文关系、当前约束；negation_scope 限定否定作用域；frame_semantics 做跨字段一致性校验。NLU 模型转换与规则 fallback 是同一理解子系统的主/降级来源，不能为删除而取消模型不可用能力。
- PrepareContext 的 ordinal 引用与分类替换依赖数据库活动菜单：它补全可信 Frame 的目标及继承配额，不是第二次 Task Classification。
- Dietary ConstraintResolver 使用 Frame statements、类型化记忆、显式 carryover 建立 ResolvedConstraints；ConstraintEvaluator 产生 satisfied/violated/unknown。recipe_safety/preference_rules 和生成验证调用既有 taxonomy/evaluator，Observer 与 Final Safety 各有执行/发布生命周期。
- Observer 的 menu_progress 写入候选、去重、计数并通过 menu_coverage 计算配额；Reflector 读取进度并决定继续；Final Safety 用 allowed_names 再计算可发布覆盖率。同一个算法针对不同证据集合，不是相互冲突的完成标准。
- build_menu_search_plan 的 limit 是候选召回数（至少 5、缺口两倍），requested_count 是用户目标；MAX_MENU_CALLS_PER_BATCH 是执行批次。保留菜单召回覆盖率与普通 RecipeService 内部扫描策略。
- filter_new_tool_calls 使用 signature、tool_trace 和 remaining_calls；validate_tool_actions 是 Planner/Reflector 共用的唯一合法性/预算闸门。Executor 的 review_tool_calls 则注入不可削弱的参数，属于执行前安全防线。

