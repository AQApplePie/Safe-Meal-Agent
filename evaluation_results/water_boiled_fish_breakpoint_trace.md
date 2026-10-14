# “水煮鱼怎么做”单轮真实断点追踪

## 0. 本次追踪范围

本文件只分析下面一个请求，不包含任何其他轮次：

```text
水煮鱼怎么做
```

本次请求真实调用了本机 SafeMeal HTTP API。关键运行标识：

```text
HTTP status: 200
session_id: 3f2daaa5-c273-4247-979e-adccd51f1467
数据库用户消息 ID: 555
数据库助手消息 ID: 556
route: agent-tools-loop
route_logic: agent-tools-loop
```

完整原始响应和历史记录保存在：

```text
/tmp/safemeal_water_boiled_fish_trace.json
```

下面的“断点”表示适合在调试器中暂停的位置。参数值来自本次真实 HTTP 响应、持久化历史和代码调用关系；不是另外构造的示例值。

---

## 断点 1：`create_chat_turn()` 接收 HTTP 请求

文件：

```text
safemeal/interfaces/http/routers/chat.py
```

真实函数：

```python
async def create_chat_turn(
    request: ChatRequest,
    turn_service: ChatTurnService,
    principal: Principal,
) -> ChatResponse
```

HTTP 请求体：

```json
{
  "message": "水煮鱼怎么做",
  "request_id": "1791094242379015000"
}
```

FastAPI 将请求体解析为 `ChatRequest`。进入函数时，核心字段是：

```python
request.message == "水煮鱼怎么做"
request.request_id == "1791094242379015000"
request.session_id is None
request.user_id is None
```

认证依赖已经把 Bearer Token 解析为 `Principal`。路由执行：

```python
bound_request = request.model_copy(
    update={"user_id": principal.storage_subject}
)
```

传给下一段代码的是：

```python
await turn_service.handle(bound_request)
```

其中：

```python
bound_request.message == "水煮鱼怎么做"
bound_request.session_id is None
bound_request.request_id == "1791094242379015000"
bound_request.user_id == <本次注册用户的 storage_subject>
```

---

## 断点 2：`ChatTurnService.handle()` 开始一轮用例

文件：

```text
safemeal/application/service/chat/chat_turn_service.py
```

真实类和方法：

```python
class ChatTurnService:
    async def handle(self, request: ChatRequest) -> ChatResponse
```

进入参数：

```python
request = ChatRequest(
    message="水煮鱼怎么做",
    request_id="1791094242379015000",
    session_id=None,
    user_id=<storage_subject>,
)
```

关键局部变量：

```python
user_id = request.user_id
```

随后调用：

```python
self._persistence.start_turn(
    request.session_id,       # None
    user_id,                  # 当前登录用户
    request.message,          # "水煮鱼怎么做"
    request_id=request.request_id,
)
```

---

## 断点 3：`ChatTurnPersistence.start_turn()` 创建会话和用户消息

文件：

```text
safemeal/application/service/chat/turn_persistence.py
```

真实方法：

```python
ChatTurnPersistence.start_turn(
    session_id: str | None,
    user_id: str,
    message: str,
    request_id: str | None,
) -> ChatTurnStart
```

进入参数：

```python
session_id = None
user_id = <storage_subject>
message = "水煮鱼怎么做"
request_id = "1791094242379015000"
```

因为 `session_id is None`，方法创建：

```python
ChatSessionCreate(
    id="3f2daaa5-c273-4247-979e-adccd51f1467",
    user_id=<storage_subject>,
    title="Chat 2026-10-04 06:10",
)
```

接着构造并保存：

```python
ChatMessageCreate(
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    message_type="user_query",
    content="水煮鱼怎么做",
    order_index=1,
    client_request_id="1791094242379015000",
    turn_status="processing",
)
```

这里：

```text
ChatMessageCreate 是真实 Pydantic 类名。
user_query 只是 ChatMessageCreate.message_type 的字段值。
```

数据库创建出的消息记录：

```json
{
  "id": 555,
  "session_id": "3f2daaa5-c273-4247-979e-adccd51f1467",
  "message_type": "user_query",
  "content": "水煮鱼怎么做",
  "order_index": 1,
  "client_request_id": "1791094242379015000",
  "turn_status": "processing"
}
```

方法返回：

```python
ChatTurnStart(
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    user_message_id=555,
    response_order_index=2,
)
```

---

## 断点 4：`ChatTurnService.handle()` 构造 `WorkflowRequest`

回到 `ChatTurnService.handle()` 后，局部变量 `turn` 的值为：

```python
turn.session_id == "3f2daaa5-c273-4247-979e-adccd51f1467"
turn.user_message_id == 555
turn.response_order_index == 2
```

然后构造：

```python
WorkflowRequest(
    user_id=<storage_subject>,
    message="水煮鱼怎么做",
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    source_message_id="555",
)
```

并调用：

```python
result = await self._workflow.run(workflow_request)
```

---

## 断点 5：`ChatWorkflow.run()` 启动外层 Workflow

文件：

```text
safemeal/application/workflow/runner.py
```

真实方法：

```python
ChatWorkflow.run(request: WorkflowRequest) -> AgentProcessResponse
```

它向外层 LangGraph 传入：

```python
{
    "request": WorkflowRequest(
        user_id=<storage_subject>,
        message="水煮鱼怎么做",
        session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
        source_message_id="555",
    )
}
```

调用代码：

```python
state = await self.graph.ainvoke({"request": request})
```

`build_chat_workflow()` 定义的实际节点顺序是：

```text
UnderstandRequestNode.__call__
→ PrepareContextNode.__call__
→ resolve_constraints
→ InvokeAgentNode.__call__
→ check_final_safety
→ SaveMemoryNode.__call__
```

---

## 断点 6：`UnderstandRequestNode.__call__()` 加载短期历史

文件：

```text
safemeal/application/workflow/nodes/understand_request.py
```

真实类和方法：

```python
class UnderstandRequestNode:
    async def __call__(self, state: WorkflowState) -> WorkflowState
```

进入时：

```python
state["request"].message == "水煮鱼怎么做"
state["request"].session_id == "3f2daaa5-c273-4247-979e-adccd51f1467"
state["request"].source_message_id == "555"
```

它调用：

```python
self._context_builder.load_recent_history(
    user_id=<storage_subject>,
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    source_message_id="555",
    fallback=[],
)
```

由于这是第一条用户消息，历史结果为：

```python
history == []
recent == []
```

---

## 断点 7：`RequestUnderstandingGateway.understand()` 调用失败并回退

`UnderstandRequestNode.__call__()` 首先尝试：

```python
await self._gateway.understand(
    "水煮鱼怎么做",
    [],
)
```

本次真实异常类型：

```text
ConnectError
```

所以执行规则回退：

```python
self._fallback.understand(
    "水煮鱼怎么做",
    [],
)
```

其中 `self._fallback` 的真实类型是：

```python
RequestUnderstandingService
```

回退结果又被更新为：

```python
{
    "backend": "local_model:rules_fallback",
    "understanding_status": "fallback",
    "fallback_used": True,
    "validation_errors": ("ConnectError",),
}
```

---

## 断点 8：`RequestUnderstandingService.understand()` 解析请求

文件：

```text
safemeal/application/service/chat/request_understanding.py
```

真实调用：

```python
RequestUnderstandingService().understand(
    message="水煮鱼怎么做",
    recent_context=[],
)
```

关键解析过程：

```python
text = "水煮鱼怎么做"
```

`_DETAIL_TARGET_PATTERN` 匹配到：

```text
目标部分：水煮鱼
请求字段：怎么做
```

因此局部变量形成：

```python
target_name = "水煮鱼"
fields = ["steps"]
tasks = [RequestTask(kind="recipe_detail")]
```

最终输出的完整 `RequestFrame`：

```json
{
  "tasks": [{"kind": "recipe_detail"}],
  "memory_updates": [],
  "current_constraints": [],
  "turn_preferences": [],
  "statements": [],
  "participants": [],
  "context_relation": "new_task",
  "operation": null,
  "canonical": true,
  "target": {
    "recipe_name": "水煮鱼",
    "ingredient": null,
    "menu_category": null
  },
  "requested_fields": ["steps"],
  "exact_match_required": true,
  "recommendation_count": null,
  "servings": null,
  "meal_type": null,
  "scenario": null,
  "menu_planning": null,
  "context_needs": [
    "allergies",
    "dietary_restrictions",
    "recent_conversation"
  ],
  "confidence": 0.9,
  "understanding_status": "fallback",
  "backend": "local_model:rules_fallback",
  "fallback_used": true,
  "clarification_question": null,
  "validation_errors": ["ConnectError"]
}
```

`UnderstandRequestNode.__call__()` 返回给 LangGraph：

```python
{
    "request_frame": <上面的 RequestFrame>,
    "recent_history": [],
}
```

---

## 断点 9：`PrepareContextNode.__call__()` 构建 `ConversationContext`

文件：

```text
safemeal/application/workflow/nodes/prepare_context.py
```

真实类和方法：

```python
PrepareContextNode.__call__(state: WorkflowState)
```

它调用：

```python
AgentContextBuilder.build_chat_context(
    user_id=<storage_subject>,
    message="水煮鱼怎么做",
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    conversation_history=[],
    source_message_id="555",
    use_user_memory=True,
    request_frame=<断点 8 的 RequestFrame>,
    preloaded_history=[],
)
```

本次实际上下文加载结果：

```python
loaded_context_types == []
user_memory_count == 0
episodic_memory_count == 0
has_user_profile == False
```

由于这是 `recipe_detail`，不是菜单修改，并且没有上一轮菜单：

```python
context.context_metadata.get("active_menu") is None
```

`PrepareContextNode` 不修改目标菜名，输出仍然是：

```python
frame.target.recipe_name == "水煮鱼"
frame.context_relation == "new_task"
frame.requested_fields == ("steps",)
```

---

## 断点 10：`resolve_constraints()` 解析安全与偏好约束

文件：

```text
safemeal/application/workflow/nodes/constraints.py
```

真实函数：

```python
resolve_constraints(state: WorkflowState) -> WorkflowState
```

输入依据包括：

```python
state["request"].message == "水煮鱼怎么做"
state["request_frame"].current_constraints == ()
state["request_frame"].turn_preferences == ()
```

真实输出：

```json
{
  "allergies": {
    "active": false,
    "trigger_terms": [],
    "raw_ingredients": [],
    "excluded_ingredients": [],
    "strictness": "hard_exclusion_contextual"
  },
  "restrictions": {
    "active": false,
    "trigger_terms": [],
    "raw_ingredients": [],
    "excluded_ingredients": [],
    "strictness": "hard_exclusion_contextual"
  },
  "preferences": [],
  "resolved": {
    "hard_safety": [],
    "strong_requirements": [],
    "soft_preferences": [],
    "menu_goals": []
  }
}
```

这些结果被写入当前 `ConversationContext`，再传给 Agent。

---

## 断点 11：`InvokeAgentNode.__call__()` 调用 Agent 入口

文件：

```text
safemeal/application/workflow/nodes/invoke_agent.py
```

真实调用：

```python
await self.agent.process(
    "水煮鱼怎么做",
    "3f2daaa5-c273-4247-979e-adccd51f1467",
    context=state["context"].model_copy(deep=True),
)
```

此时传给 Agent 的关键 `ConversationContext` 内容是：

```python
context.request_frame.primary_task == "recipe_detail"
context.request_frame.target.recipe_name == "水煮鱼"
context.request_frame.requested_fields == ("steps",)
context.request_frame.exact_match_required is True
context.conversation_history == []
context.user_memories == []
context.episodic_memories == []
context.context_metadata["resolved_constraints"] == <断点 10 的结果>
```

---

## 断点 12：`AgentExecutionService.process()` 进入 Agent 六层链路

文件：

```text
safemeal/application/agent/gateway/service.py
```

真实类和方法：

```python
AgentExecutionService.process(
    query: str,
    session_id: str,
    context: ConversationContext,
) -> AgentProcessResponse
```

进入参数：

```python
query = "水煮鱼怎么做"
session_id = "3f2daaa5-c273-4247-979e-adccd51f1467"
context.request_frame.target.recipe_name = "水煮鱼"
context.request_frame.requested_fields = ("steps",)
```

随后调用 Agent LangGraph。`build_agent_graph()` 注册的节点顺序为：

```text
initialize
→ planner
→ human_approval
→ execute_tools
→ observe
→ reflect
→ respond
```

---

## 断点 13：`create_initializer_node()` 初始化 `AgentState`

文件：

```text
safemeal/application/agent/orchestration/nodes/initializer/node.py
```

真实工厂函数：

```python
create_initializer_node(...)
```

该节点读取：

```python
query == "水煮鱼怎么做"
context.request_frame.primary_task == "recipe_detail"
context.request_frame.target.recipe_name == "水煮鱼"
```

本轮不是组合菜单，因此初始化结果中：

```python
menu_execution_plan == {}
menu_task_progress == {}
```

初始执行计数可理解为：

```python
iteration = 0
tool_call_count = 0
observations = [task_context_observation]
evidence_sufficient = False
```

已记录的任务上下文 Observation 最终表现为：

```json
{
  "tools": "task_context",
  "ok": true,
  "status": "ok",
  "error_code": null,
  "has_data": true
}
```

---

## 断点 14：`create_planner_node()` 生成 `search_recipes` 调用

文件：

```text
safemeal/application/agent/orchestration/nodes/planner/node.py
```

真实工厂函数：

```python
create_planner_node(
    model_gateway: AgentModelGateway,
    tool_executor: ToolExecutor,
)
```

Planner 读取的关键参数：

```python
primary_task = "recipe_detail"
recipe_name = "水煮鱼"
requested_fields = ("steps",)
exact_match_required = True
```

它生成的实际工具参数：

```json
{
  "name_contains": "水煮鱼",
  "exact_name": true,
  "required_fields": ["steps"],
  "limit": 1
}
```

参数含义：

```text
name_contains="水煮鱼"：查询目标名称。
exact_name=true：不能返回“豆芽水煮鱼片”等近似菜替代。
required_fields=["steps"]：结果必须具有做法步骤。
limit=1：精确查询只需要一条记录。
```

Planner 产生的计划包含一个 `ToolCall`：

```text
tool_name = search_recipes
```

---

## 断点 15：`create_approval_node()` 判断是否需要人工批准

文件：

```text
safemeal/application/agent/orchestration/nodes/approval.py
```

真实工厂函数：

```python
create_approval_node(approval_tool_names)
```

`search_recipes` 是只读查询工具，不属于需要人工批准的写操作。本轮没有中断，也没有产生 approval request，因此路由继续进入 `execute_tools`。

---

## 断点 16：`create_executor_node()` 执行工具

文件：

```text
safemeal/application/agent/orchestration/nodes/executor/node.py
```

真实工厂函数：

```python
create_executor_node(tool_executor: ToolExecutor)
```

传给 `ToolExecutor` 的实际参数：

```json
{
  "tool": "search_recipes",
  "args": {
    "name_contains": "水煮鱼",
    "exact_name": true,
    "required_fields": ["steps"],
    "limit": 1
  }
}
```

工具层最终使用的 `effective_args`：

```json
{
  "name_contains": "水煮鱼",
  "exact_name": true,
  "required_fields": ["steps"],
  "limit": 1
}
```

本轮没有额外安全约束，因此 `args` 与 `effective_args` 完全相同。

工具真实返回摘要：

```json
{
  "status": "FOUND",
  "result_count": 1,
  "result_names": ["水煮鱼"],
  "result_categories": []
}
```

证据来源：

```json
{
  "source": "data/recipe.json",
  "tool": "search_recipes",
  "call_id": "exact-recipe-search",
  "query": null,
  "evidence_call_ids": []
}
```

工具执行后形成的 Observation 摘要：

```json
{
  "tools": "search_recipes",
  "ok": true,
  "status": "ok",
  "error_code": null,
  "has_data": true
}
```

---

## 断点 17：`observe()` 把工具结果写回 `AgentState`

文件：

```text
safemeal/application/agent/orchestration/nodes/observer
```

真实入口函数：

```python
observe(state: AgentState) -> AgentState
```

本轮为 `recipe_detail`，所以 `observe()` 主要保留精确食谱证据，不进行菜单配额计算。

写回后的关键状态：

```python
tool_call_count = 1
observations = [
    <task_context Observation>,
    <search_recipes Observation>,
]
menu_execution_plan = {}
menu_task_progress = {}
```

---

## 断点 18：`create_reflector_node()` 检查证据是否足够

文件：

```text
safemeal/application/agent/orchestration/nodes/reflector/node.py
```

真实工厂函数：

```python
create_reflector_node(
    model_gateway: AgentModelGateway,
    tool_executor: ToolExecutor,
)
```

Reflector 检查：

```text
是否找到精确名称“水煮鱼”：是
是否包含 requested_fields=[steps]：是
结果数量是否满足 limit=1：是
是否需要再次搜索：否
```

实际输出：

```json
{
  "rationale": "确定性工具已返回满足成功标准的可用证据，无需继续补查。",
  "evidence_sufficient": true,
  "missing_information": []
}
```

`_after_reflection()` 因此将执行方向设为：

```text
respond
```

本轮不会再次进入 Planner。

---

## 断点 19：`create_responder_node()` 生成回答

文件：

```text
safemeal/application/agent/aggregation/responder.py
```

真实工厂函数：

```python
create_responder_node(model_gateway: AgentModelGateway)
```

Responder 使用的核心事实：

```python
target_recipe_name = "水煮鱼"
requested_fields = ("steps",)
exact_match_required = True
evidence_sufficient = True
search_result_name = "水煮鱼"
search_result_source = "data/recipe.json"
```

实际生成的回答：

```text
水煮鱼的做法：
1. 1:草鱼，洗好鱼骨和鱼肉分开，鱼骨剁块，鱼肉片成片，加入适量的料酒，生抽，一个鸡蛋清，盐，鸡精，胡椒粉干淀粉抓匀腌20分钟。
2. 2:准备爱吃的各种青菜，洗好备用。
3. 3:调料，选好备用。
4. 4:郫县豆瓣酱，麻辣块，我这里用的是红九九。
5. 5:葱姜蒜，香菜，切好备用。
6. 6:起锅烧油，油热加入葱姜蒜爆锅，再加入豆瓣酱炒出红油。
7. 7:加入花椒，八角，桂皮，香叶，翻炒加入麻辣块炒出红油，加水后捞出料渣。
8. 8:加水后，加适量的盐，鸡精调味，加入洗好的青菜，炖熟。
9. 9:捞出，放入盘中垫底。
10. 10:接着放入鱼骨，炖熟，依次再放入鱼肉片，炖熟捞出。
11. 11:把鱼肉连汤一起倒出。
12. 12:上面撒上树椒段，麻椒，香菜，锅内加油烧开浇在上面，就可以吃了。
```

Agent 图结束时的执行统计：

```json
{
  "iteration": 1,
  "tool_call_count": 1,
  "budget_exhausted": false,
  "loop_stop_reason": "",
  "evidence_sufficient": true,
  "missing_information": []
}
```

---

## 断点 20：`check_final_safety()` 进行最终安全检查

文件：

```text
safemeal/application/workflow/nodes/safety.py
```

真实函数：

```python
check_final_safety(state: WorkflowState) -> WorkflowState
```

它接收 `InvokeAgentNode` 返回的 `AgentProcessResponse`，结合断点 10 的约束进行最终检查。

本轮没有过敏或忌口，实际审核结果：

```json
{
  "recipe_reviews": [
    {
      "name": "水煮鱼",
      "decision": "passed",
      "allergy_status": "safe",
      "preference_status": "not_applicable",
      "preferences": []
    }
  ],
  "safety_review": "passed"
}
```

---

## 断点 21：`SaveMemoryNode.__call__()` 判断是否写入记忆

文件：

```text
safemeal/application/workflow/nodes/save_memory.py
```

真实类和方法：

```python
SaveMemoryNode.__call__(state: WorkflowState)
```

当前 `RequestFrame` 中：

```python
memory_updates == ()
```

所以本轮不会写入偏好、忌口或过敏记忆。

最终统计：

```python
user_memory_count == 0
episodic_memory_count == 0
has_user_profile == False
```

---

## 断点 22：`ChatWorkflow.run()` 返回 `AgentProcessResponse`

外层 Workflow 完成后，`ChatWorkflow.run()` 从最终状态读取：

```python
result = state["result"]
```

并写入：

```python
result.metadata["agent_status"] = result.status
```

本次核心结果：

```python
result.status == "ok"
result.route == "agent-tools-loop"
result.message.startswith("水煮鱼的做法：")
result.metadata["agent_status"] == "ok"
result.metadata["safety_review"] == "passed"
```

---

## 断点 23：`ChatTurnPersistence.save_agent_response()` 保存回答

回到 `ChatTurnService.handle()` 后，实际调用：

```python
self._persistence.save_agent_response(
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    user_id=<storage_subject>,
    user_message_id=555,
    response_order_index=2,
    response=<断点 19 的完整回答>,
    route="agent-tools-loop",
    route_logic="agent-tools-loop",
    sources=(<data/recipe.json 的证据来源>,),
    metadata=<完整 Agent metadata>,
)
```

内部构造：

```python
ChatMessageCreate(
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    message_type="agent_response",
    content=<完整水煮鱼步骤>,
    message_metadata=<完整 Agent metadata>,
    order_index=2,
    reply_to_message_id=555,
)
```

数据库创建结果：

```json
{
  "id": 556,
  "session_id": "3f2daaa5-c273-4247-979e-adccd51f1467",
  "message_type": "agent_response",
  "order_index": 2,
  "reply_to_message_id": 555
}
```

同时更新原消息：

```python
ChatMessageUpdate(turn_status="completed")
```

因此 ID 555 的最终状态从：

```text
processing
```

变为：

```text
completed
```

---

## 断点 24：`ChatTurnService.handle()` 构造最终 `ChatResponse`

最终返回对象：

```python
ChatResponse(
    message=<水煮鱼的 12 个做法步骤>,
    session_id="3f2daaa5-c273-4247-979e-adccd51f1467",
    message_id="556",
    route="agent-tools-loop",
    route_logic="agent-tools-loop",
    sources=(
        {
            "source": "data/recipe.json",
            "tool": "search_recipes",
            "call_id": "exact-recipe-search",
        },
    ),
    recipe=None,
    metadata=<完整执行 metadata>,
)
```

HTTP 层最终返回：

```text
HTTP 200
```

---

## 最终状态总览

```json
{
  "request_task": "recipe_detail",
  "context_relation": "new_task",
  "target_recipe": "水煮鱼",
  "requested_fields": ["steps"],
  "exact_match_required": true,
  "request_understanding_backend": "local_model:rules_fallback",
  "understanding_error": "ConnectError",
  "tool": "search_recipes",
  "tool_call_count": 1,
  "tool_status": "FOUND",
  "tool_result_name": "水煮鱼",
  "evidence_source": "data/recipe.json",
  "reflect_evidence_sufficient": true,
  "final_safety": "passed",
  "agent_status": "ok",
  "http_status": 200
}
```

## 本次追踪暴露出的表现问题

链路和意图识别是正确的，但最终步骤出现了重复编号：

```text
1. 1:草鱼……
2. 2:准备……
```

这表明原始 `data/recipe.json` 的步骤文本自身带有 `1:`、`2:`，而 `create_responder_node()` 渲染时又添加了一层 Markdown 序号。问题位于食谱步骤规范化或响应渲染层，不是 Request Understanding、Planner 或 Tool 参数错误。

另外，本轮不是菜单任务，但响应 metadata 中仍出现：

```json
{
  "active_menu": {
    "plan": {},
    "progress": {}
  }
}
```

这对当前单轮回答没有影响，但在长对话中可能覆盖此前的有效 `active_menu`。这是需要单独评估的 Conversation Context 生命周期问题。
