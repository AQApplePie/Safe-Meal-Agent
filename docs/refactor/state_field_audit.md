# 状态字段审计

Decision：KEEP、REMOVE、DERIVE、UNCERTAIN。

## AgentState

| 字段 | 写入者 | 主要读取者/序列化 | Decision | 理由 |
|---|---|---|---|---|
| messages | Gateway、Responder | Initializer、Checkpoint、Gateway response | KEEP | LangGraph 消息生命周期 |
| agent_context | Gateway、Initializer、Planner | 所有可信上下文消费者、Resume | KEEP | Checkpoint 恢复边界 |
| intent | Planner | Responder、Gateway、Final Safety | KEEP | 稳定执行分类，不应重复推导 |
| question | Initializer | Planner/Reflector/Responder | KEEP | 当前轮文本，与历史不同 |
| conversation_history | Initializer | Model prompts | KEEP | 明确排除当前问题 |
| pending_calls | Planner/Reflector/Approval/Observer | Approval、Executor、Gateway interrupt | KEEP | 可恢复的执行队列 |
| tool_results | Executor/Observer | Observer | KEEP | 单节点间瞬时原始结果 |
| observations | Initializer/Observer | Planner、Reflector、Responder、Gateway | KEEP | 标准证据集合 |
| planning_rationale | Planner | Responder router | KEEP | 路由可解释性 |
| reflection_rationale | Reflector | Responder、Gateway metadata | KEEP | 完成决策可解释性 |
| evidence_sufficient | Reflector | Responder、Gateway | KEEP | has-results 不等于 complete |
| missing_information | Reflector | Model answer、Gateway | KEEP | PARTIAL 的确定原因 |
| direct_answer | Planner/Approval | Responder | KEEP | 无工具和拒绝路径 |
| iteration/max_iterations | Initializer/Executor | Reflector | KEEP | 循环保护 |
| route | nodes | graph routing、Responder | KEEP | 图控制状态 |
| router/sources | Responder | Gateway/API | KEEP | 输出契约 |
| dietary_constraints | Initializer | Tool Policy、Observer、Responder、Resume | KEEP | 冻结硬约束编译产物 |
| executed_call_signatures | Executor | action policy | KEEP | 重复调用控制 |
| tool_call_count/max_tool_calls | Initializer/Executor | action policy、metadata | KEEP | Tool Budget |
| max_model_tokens/max_model_cost | Initializer | action policy | KEEP | Model Budget |
| budget_exhausted/loop_stop_reason | action policy/nodes | Responder、metadata | KEEP | 可解释的有界降级 |
| menu_execution_plan/menu_task_progress | Initializer/Observer | Planner、Reflector、Safety、下一轮上下文 | KEEP | 菜单目标与可变进度不同 |
| tool_trace | Executor | duplicate policy、metadata | KEEP | 保存 effective args，Observation 不包含 |
| human_approved | Approval | 无 | REMOVE | interrupt 已保存审批控制 |
| approval_required | Approval | 无；外部同名 metadata 独立生成 | REMOVE | 图状态无消费者 |
| safety_gate_blocked | Planner | 无；route 已表达 | REMOVE | 同义状态 |

## AgentContext

`conversation_history`、记忆、画像、`requirements`、`request_frame`、observations 和 metadata 均有独立消费者，保留。`dietary_constraints` 是冻结编译结果，保留。

`resolved_constraints`：REMOVE。它只在 Constraint Resolver 写入，实际语义已由 `requirements.resolved` 持有。

## WorkflowState

- KEEP：request、context、result、requirements、request_frame、recent_history、active_menu。
- REMOVE：resolved_constraints。没有节点读取，Final Safety 使用 requirements。
- `recent_history` 与 `active_menu` 是 Understanding 到 Context Preparation 的一次性预加载结果，避免数据库重复读取，不是 Context 副本。

## Metadata、Observation、ToolResult

- ToolResult 只跨 Executor → Observer，随后清空。
- Observation 是模型推理、完成度和 Final Safety 使用的标准证据。
- Tool trace 保存 proposed/effective args 和执行摘要，用于审计及重复结果识别。
- Response metadata 是跨 Workflow、HTTP、持久化和下一轮菜单引用的外部契约，不等同于 LangGraph 内部状态。


## 本次重新扫描的逐字段索引

每个字段均保留。下列索引覆盖属性、字符串键、get/getattr、字典构造与序列化使用；源码引用是消费者定位线索，不能单凭引用数判断可删除。上表给出业务生命周期判断。全部 AgentState 经 LangGraph Checkpoint 保存；AgentContext 以 JSON 保存到 AgentState；WorkflowState 仅外图本轮状态，外图未装配 Checkpointer。

### AgentState

| field_name | defined_in | 读写定位（最多 5 处） | serialized_to / checkpoint | external contract | decision |
|---|---|---|---|---|---|
| intent | safemeal/agent/contracts/state.py:56 | safemeal/infrastructure/nlu/local_request_understanding.py:213<br>safemeal/agent/gateway/service.py:457<br>safemeal/agent/workflow/nodes/save_memory.py:19<br>safemeal/agent/workflow/nodes/safety.py:61<br>safemeal/agent/workflow/nodes/safety.py:94 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| messages | safemeal/agent/contracts/state.py:56 | safemeal/modules/conversation/application/turn_persistence.py:193<br>safemeal/modules/conversation/application/turn_persistence.py:61<br>safemeal/modules/conversation/application/turn_persistence.py:64<br>safemeal/modules/conversation/application/turn_persistence.py:106<br>safemeal/modules/conversation/application/turn_persistence.py:116 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| agent_context | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:177<br>safemeal/agent/gateway/service.py:229<br>safemeal/agent/runtime/aggregation/responder.py:29<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:107<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:41 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| question | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:231<br>safemeal/agent/runtime/aggregation/responder.py:81<br>safemeal/agent/runtime/aggregation/responder.py:94<br>safemeal/agent/runtime/aggregation/responder.py:121<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:108 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| conversation_history | safemeal/agent/contracts/state.py:56 | safemeal/infrastructure/llm/openai_language_model_gateway.py:352<br>safemeal/agent/contracts/context.py:34<br>safemeal/agent/gateway/service.py:174<br>safemeal/agent/workflow/nodes/prepare_context.py:49<br>safemeal/agent/workflow/nodes/understand_request.py:38 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| pending_calls | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:232<br>safemeal/agent/gateway/service.py:184<br>safemeal/agent/gateway/service.py:185<br>safemeal/agent/gateway/service.py:196<br>safemeal/agent/runtime/orchestration/routing.py:8 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| tool_results | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/nodes/initializer/node.py:111<br>safemeal/agent/runtime/orchestration/nodes/observer/node.py:78<br>safemeal/agent/runtime/orchestration/nodes/observer/node.py:138<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:60 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| observations | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:287<br>safemeal/agent/gateway/service.py:361<br>safemeal/agent/workflow/context/builder.py:257<br>safemeal/agent/workflow/context/builder.py:258<br>safemeal/agent/workflow/nodes/prepare_context.py:143 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| planning_rationale | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/aggregation/responder.py:152<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:128<br>safemeal/agent/runtime/orchestration/nodes/planner/constraints.py:165<br>safemeal/agent/runtime/orchestration/nodes/planner/node.py:88 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| reflection_rationale | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:384<br>safemeal/agent/runtime/aggregation/responder.py:151<br>safemeal/agent/runtime/aggregation/responder.py:97<br>safemeal/agent/runtime/aggregation/responder.py:124<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:129 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| evidence_sufficient | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:356<br>safemeal/agent/gateway/service.py:385<br>safemeal/agent/gateway/service.py:343<br>safemeal/agent/runtime/aggregation/responder.py:98<br>safemeal/agent/runtime/aggregation/responder.py:125 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| missing_information | safemeal/agent/contracts/state.py:56 | safemeal/modules/dietary/application/constraints.py:472<br>safemeal/modules/dietary/application/constraints.py:476<br>safemeal/modules/dietary/application/constraints.py:480<br>safemeal/agent/safety/answer.py:68<br>safemeal/agent/safety/dietary_safety_service.py:207 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| direct_answer | safemeal/agent/contracts/state.py:56 | safemeal/agent/contracts/decisions.py:52<br>safemeal/agent/runtime/aggregation/responder.py:69<br>safemeal/agent/runtime/aggregation/responder.py:104<br>safemeal/agent/runtime/aggregation/responder.py:105<br>safemeal/agent/runtime/orchestration/nodes/approval.py:23 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| iteration | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:352<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:113<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:28<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:61 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| max_iterations | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/nodes/initializer/node.py:114<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:29<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:113<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:77 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| route | safemeal/agent/contracts/state.py:56 | safemeal/interfaces/http/routers/chat.py:110<br>safemeal/modules/conversation/application/turn_persistence.py:97<br>safemeal/agent/gateway/service.py:241<br>safemeal/agent/gateway/service.py:146<br>safemeal/agent/gateway/chat_turn_service.py:120 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| router | safemeal/agent/contracts/state.py:56 | safemeal/interfaces/http/routers/auth.py:91<br>safemeal/interfaces/http/routers/chat.py:350<br>safemeal/interfaces/http/routers/knowledge.py:183<br>safemeal/agent/gateway/service.py:282<br>safemeal/agent/runtime/aggregation/responder.py:159 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| sources | safemeal/agent/contracts/state.py:56 | safemeal/interfaces/http/routers/chat.py:111<br>safemeal/modules/conversation/application/turn_persistence.py:99<br>safemeal/agent/gateway/service.py:286<br>safemeal/agent/gateway/chat_turn_service.py:122<br>safemeal/agent/gateway/chat_turn_service.py:89 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| dietary_constraints | safemeal/agent/contracts/state.py:56 | safemeal/infrastructure/llm/openai_language_model_gateway.py:354<br>safemeal/agent/safety/dietary_safety_service.py:72<br>safemeal/agent/safety/dietary_safety_service.py:74<br>safemeal/agent/gateway/service.py:230<br>safemeal/agent/workflow/nodes/prepare_context.py:151 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| executed_call_signatures | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/action_policy.py:44<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:120<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:63<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:64 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| tool_call_count | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:353<br>safemeal/agent/runtime/orchestration/action_policy.py:40<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:121<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:62 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| max_tool_calls | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/action_policy.py:40<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:122 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| max_model_tokens | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/action_policy.py:54<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:123 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| max_model_cost | safemeal/agent/contracts/state.py:56 | safemeal/agent/runtime/orchestration/action_policy.py:56<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:124 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| budget_exhausted | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:354<br>safemeal/agent/runtime/aggregation/responder.py:128<br>safemeal/agent/runtime/aggregation/responder.py:107<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:125<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:129 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| loop_stop_reason | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:355<br>safemeal/agent/runtime/aggregation/responder.py:129<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:126<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:197<br>safemeal/agent/runtime/orchestration/nodes/reflector/node.py:74 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| menu_execution_plan | safemeal/agent/contracts/state.py:56 | safemeal/agent/context/history.py:57<br>safemeal/agent/gateway/service.py:423<br>safemeal/agent/gateway/service.py:413<br>safemeal/agent/gateway/service.py:414<br>safemeal/agent/gateway/service.py:415 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| menu_task_progress | safemeal/agent/contracts/state.py:56 | safemeal/agent/context/history.py:58<br>safemeal/agent/gateway/service.py:417<br>safemeal/agent/gateway/service.py:418<br>safemeal/agent/gateway/service.py:419<br>safemeal/agent/gateway/service.py:436 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
| tool_trace | safemeal/agent/contracts/state.py:56 | safemeal/agent/gateway/service.py:372<br>safemeal/agent/runtime/orchestration/action_policy.py:46<br>safemeal/agent/runtime/orchestration/nodes/initializer/node.py:133<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:67<br>safemeal/agent/runtime/orchestration/nodes/executor/node.py:29 | AgentState JSON/typed checkpoint | Gateway 选择输出；非整对象 HTTP | KEEP |
### AgentContext

| field_name | defined_in | 读写定位（最多 5 处） | serialized_to / checkpoint | external contract | decision |
|---|---|---|---|---|---|
| conversation_history | safemeal/agent/contracts/context.py:17 | safemeal/infrastructure/llm/openai_language_model_gateway.py:352<br>safemeal/agent/gateway/service.py:174<br>safemeal/agent/workflow/nodes/prepare_context.py:49<br>safemeal/agent/workflow/nodes/understand_request.py:38<br>safemeal/agent/runtime/aggregation/responder.py:95 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| user_memories | safemeal/agent/contracts/context.py:17 | safemeal/infrastructure/operations/health.py:60<br>safemeal/infrastructure/persistence/db/models/user_memory.py:27<br>safemeal/infrastructure/persistence/migrations/versions/20260705_0001_initial_application_schema.py:274<br>safemeal/infrastructure/persistence/migrations/versions/20260705_0001_initial_application_schema.py:352<br>safemeal/infrastructure/persistence/migrations/versions/20260705_0001_initial_application_schema.py:355 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| user_profile | safemeal/agent/contracts/context.py:17 | safemeal/infrastructure/llm/openai_language_model_gateway.py:353<br>safemeal/infrastructure/nlu/local_request_understanding.py:299<br>safemeal/shared/contracts/request_frame.py:118<br>safemeal/agent/understanding/request_understanding.py:245<br>safemeal/agent/safety/dietary_safety_service.py:77 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| dietary_constraints | safemeal/agent/contracts/context.py:17 | safemeal/infrastructure/llm/openai_language_model_gateway.py:354<br>safemeal/agent/safety/dietary_safety_service.py:72<br>safemeal/agent/safety/dietary_safety_service.py:74<br>safemeal/agent/gateway/service.py:230<br>safemeal/agent/workflow/nodes/prepare_context.py:151 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| requirements | safemeal/agent/contracts/context.py:17 | safemeal/agent/safety/dietary_safety_service.py:68<br>safemeal/agent/safety/dietary_safety_service.py:69<br>safemeal/agent/safety/dietary_safety_service.py:70<br>safemeal/agent/safety/dietary_safety_service.py:71<br>safemeal/agent/safety/dietary_safety_service.py:138 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| intent | safemeal/agent/contracts/context.py:17 | safemeal/infrastructure/nlu/local_request_understanding.py:213<br>safemeal/agent/gateway/service.py:457<br>safemeal/agent/workflow/nodes/save_memory.py:19<br>safemeal/agent/workflow/nodes/safety.py:61<br>safemeal/agent/workflow/nodes/safety.py:94 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| request_frame | safemeal/agent/contracts/context.py:17 | safemeal/agent/safety/dietary_safety_service.py:82<br>safemeal/agent/gateway/service.py:373<br>safemeal/agent/gateway/service.py:375<br>safemeal/agent/gateway/service.py:374<br>safemeal/agent/workflow/context/builder.py:206 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| episodic_memories | safemeal/agent/contracts/context.py:17 | safemeal/agent/gateway/service.py:359<br>safemeal/agent/workflow/context/builder.py:224<br>safemeal/agent/workflow/context/builder.py:254<br>safemeal/agent/workflow/context/builder.py:255<br>safemeal/agent/workflow/context/builder.py:191 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| observations | safemeal/agent/contracts/context.py:17 | safemeal/agent/gateway/service.py:287<br>safemeal/agent/gateway/service.py:361<br>safemeal/agent/workflow/context/builder.py:257<br>safemeal/agent/workflow/context/builder.py:258<br>safemeal/agent/workflow/nodes/prepare_context.py:143 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
| context_metadata | safemeal/agent/contracts/context.py:17 | safemeal/agent/gateway/service.py:408<br>safemeal/agent/gateway/service.py:421<br>safemeal/agent/gateway/service.py:422<br>safemeal/agent/gateway/service.py:409<br>safemeal/agent/workflow/context/builder.py:226 | agent_context JSON/checkpoint | process 输入；Resume 可信上下文 | KEEP |
### WorkflowState

| field_name | defined_in | 读写定位（最多 5 处） | serialized_to / checkpoint | external contract | decision |
|---|---|---|---|---|---|
| request | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/workflow/runner.py:15<br>safemeal/agent/workflow/runner.py:27<br>safemeal/agent/workflow/nodes/prepare_context.py:26<br>safemeal/agent/workflow/nodes/understand_request.py:36<br>safemeal/agent/workflow/nodes/resume_agent.py:16 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| context | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/workflow/nodes/prepare_context.py:141<br>safemeal/agent/workflow/nodes/prepare_context.py:163<br>safemeal/agent/workflow/nodes/prepare_context.py:142<br>safemeal/agent/workflow/nodes/prepare_context.py:49<br>safemeal/agent/workflow/nodes/understand_request.py:38 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| result | safemeal/agent/contracts/workflow/models.py:29 | safemeal/interfaces/http/answer_stream.py:72<br>safemeal/interfaces/http/answer_stream.py:91<br>safemeal/interfaces/http/answer_stream.py:58<br>safemeal/infrastructure/ingestion/worker.py:39<br>safemeal/agent/workflow/runner.py:16 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| requirements | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/safety/dietary_safety_service.py:68<br>safemeal/agent/safety/dietary_safety_service.py:69<br>safemeal/agent/safety/dietary_safety_service.py:70<br>safemeal/agent/safety/dietary_safety_service.py:71<br>safemeal/agent/safety/dietary_safety_service.py:138 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| request_frame | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/safety/dietary_safety_service.py:82<br>safemeal/agent/gateway/service.py:373<br>safemeal/agent/gateway/service.py:375<br>safemeal/agent/gateway/service.py:374<br>safemeal/agent/workflow/context/builder.py:206 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| recent_history | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/workflow/nodes/prepare_context.py:41<br>safemeal/agent/workflow/nodes/understand_request.py:82 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |
| active_menu | safemeal/agent/contracts/workflow/models.py:29 | safemeal/agent/context/history.py:53<br>safemeal/agent/gateway/service.py:421<br>safemeal/agent/gateway/service.py:433<br>safemeal/agent/gateway/service.py:441<br>safemeal/agent/gateway/service.py:447 | 外图本轮状态，无 checkpoint | Workflow 内部；result 发布至 HTTP | KEEP |

### AgentContext 各字段独立消费者

- conversation_history：Initializer 的 Prompt 历史；Gateway 的消息输入。messages 用于图消息 reducer，question 用于当前问题，不能合并生命周期。
- user_memories：ConstraintResolver、Memory Observation、SaveMemory 的类型化事实。
- user_profile：task_context 和饮食偏好；has_user_profile 输出审计。
- requirements：Executor/Tool Policy、推荐工具强要求、Final Safety；完整约束包括偏好和 provenance。
- dietary_constraints：冻结硬约束、工具参数注入、Observer 过滤以及 Resume；requirements 与编译产物不是同义对象。
- intent：task_context 的执行类型，Planner 写回；不是 Frame 的分类副本（内部枚举映射不同）。
- request_frame：配额/数量/目标/字段及作用域权威语义；Planner 消费，Final Safety 限量。
- episodic_memories：上下文窗口/模型记忆证据；计数进入 metadata。
- observations：外部可信上下文证据，由 Initializer 验证后并入 runtime evidence。
- context_metadata：理解后端、活动菜单、分类替换、用户标识和加载类型；下一轮与 Resume 消费。

### WorkflowState 写入与读取

| 字段 | written_by | read_by |
|---|---|---|
| request | runner / ResumeAgentNode | Understanding、PrepareContext、Constraints、InvokeAgent、SaveMemory |
| context | PrepareContext / Constraints / ResumeAgentNode | InvokeAgent、Constraints、Safety、SaveMemory |
| result | InvokeAgent / ResumeAgent / Safety / SaveMemory | Safety、SaveMemory、runner |
| requirements | Constraints | Final Safety |
| request_frame | Understanding / PrepareContext | PrepareContext、Constraints 的 context Frame、Final Safety |
| recent_history | Understanding | PrepareContext/Builder（预加载，避免二次 DB 读取） |
| active_menu | Understanding | PrepareContext/Builder；context_metadata 成为内图/下一轮契约 |

### 数据边界检查

`AgentState.messages` 使用 `add_messages` reducer；其余字段覆盖写入。`ContractCheckpointSerializer` 保留 ToolCall/Observation/Intent 等可信类型，JSON 转换不能随意删除。`SqliteCheckpointSaver`、线程化及 Postgres 适配器仍保留。当前测试覆盖序列化往返与 approval interrupt/resume；没有验证所有历史版本检查点迁移。

metadata 的顶层 evidence_sufficient/missing_information 与 reflect 子对象有重复；HTTP/SSE/持久化对整个 metadata 暴露，消费者并不限于 Python 内部，因此列为 UNCERTAIN，保留外部契约。observations metadata 仅摘要，response.evidence 是内部发布复核用完整数据，runner 发布前清空 evidence。tool_trace 记录实际工具调用，不将 task_context/user_memory_context/dietary_context 计作执行调用。
