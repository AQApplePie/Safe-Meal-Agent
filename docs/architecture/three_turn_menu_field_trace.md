# SafeMeal 同会话三轮菜单对话字段追踪

本文按照项目真实调用顺序解释下面三轮输入：

1. 请给我推荐一个农村流水席，要求1道凉菜、2道素菜、3道荤菜、4道热菜、1道主食、1道汤。
2. 请重新推荐荤菜
3. 第三个荤菜怎么做？

文中的字段分为三类：

- 确定值：可以仅根据当前代码和输入精确得到。
- 运行时值：由登录用户、数据库自增 ID、UUID 或真实菜谱数据决定。
- 示例符号：用尖括号表示，例如 <SESSION_ID>、<新荤菜3名称>，它不是代码中的真实字符串。

## 一、总调用顺序

每一轮都会经过同一条主链：

    HTTP ChatRequest
      → ChatTurnService.handle
      → ChatTurnPersistence.start_turn
      → WorkflowRequest
      → UnderstandRequestNode
      → RequestFrame
      → PrepareContextNode
      → AgentContext
      → resolve_constraints
      → AgentExecutionService.process
      → Inner Agent initialize
      → planner
      → executor
      → observer
      → reflector
      → responder
      → check_final_safety
      → ChatTurnPersistence.save_agent_response
      → ChatResponse

关键代码位置：

- HTTP 请求/响应字段：safemeal/modules/conversation/contracts/chat/turn.py
- 单轮协调：safemeal/agent/gateway/chat_turn_service.py
- 单轮持久化：safemeal/modules/conversation/application/turn_persistence.py
- 外层 Workflow 状态：safemeal/agent/contracts/workflow/models.py
- 请求理解契约：safemeal/shared/contracts/request_frame.py
- 上下文装配：safemeal/agent/workflow/context/builder.py
- 菜单修改与顺序引用：safemeal/agent/context/menu_planning.py
- 菜单执行状态：safemeal/agent/contracts/menu_planning.py
- 内层 Agent 状态：safemeal/agent/contracts/state.py
- 菜单 Planner：safemeal/agent/runtime/orchestration/nodes/planner/menu_planning.py
- 菜单进度归约：safemeal/agent/runtime/orchestration/nodes/observer/menu_progress.py
- 跨轮活动菜单合并：safemeal/agent/context/active_menu.py

## 二、会话级运行时标识

为便于阅读，以下使用：

    user_id = <AUTHENTICATED_USER_ID>
    session_id = <SESSION_ID>

第一轮如果请求没有 session_id，ChatTurnPersistence.start_turn 会生成：

    session_id = str(uuid4())

三轮必须持续使用同一个 session_id。否则第二轮无法读取第一轮的 active_menu，第三轮也无法解析“第三个荤菜”。

假设数据库分配：

    第一轮 user_message_id = <U1>
    第一轮 agent_message_id = <A1>
    第二轮 user_message_id = <U2>
    第二轮 agent_message_id = <A2>
    第三轮 user_message_id = <U3>
    第三轮 agent_message_id = <A3>

这些 ID 是数据库运行时值，文档不能提前确定。

# 三、第一轮：创建 12 道流水席菜单

## 3.1 ChatRequest

类：

    safemeal.modules.conversation.contracts.chat.turn.ChatRequest

进入 ChatTurnService.handle 时：

    ChatRequest(
        message="请给我推荐一个农村流水席，要求1道凉菜、2道素菜、3道荤菜、4道热菜、1道主食、1道汤。",
        session_id=None,
        request_id=<客户端可选幂等ID>,
        user_id=<AUTHENTICATED_USER_ID>,
    )

字段说明：

- message：用户原始输入。
- session_id：第一轮通常为 None，由持久化服务创建。
- request_id：防止客户端重复提交；不是 Agent thread ID。
- user_id：由 HTTP 认证层绑定，不应该相信请求正文自行声明的用户。

## 3.2 ChatTurnStart

ChatTurnService 调用：

    ChatTurnPersistence.start_turn(
        session_id=None,
        user_id=<AUTHENTICATED_USER_ID>,
        message=<第一轮原文>,
        request_id=<客户端可选幂等ID>,
    )

持久化结果：

    ChatTurnStart(
        session_id=<SESSION_ID>,
        user_message_id=<U1>,
        response_order_index=2,
    )

数据库用户消息主要字段：

    message_type = "user_query"
    content = <第一轮原文>
    order_index = 1
    turn_status = "processing"
    client_request_id = <客户端可选幂等ID>

## 3.3 WorkflowRequest

ChatTurnService 构造：

    WorkflowRequest(
        user_id=<AUTHENTICATED_USER_ID>,
        message=<第一轮原文>,
        session_id=<SESSION_ID>,
        source_message_id=str(<U1>),
        history=[],
        context=None,
        use_user_memory=True,
        resume_approved=None,
    )

source_message_id 非常重要。上下文读取使用它定位“当前用户消息之前”的历史，避免把当前问题再次当成历史输入。

## 3.4 UnderstandRequestNode 输入状态

WorkflowState 此时主要为：

    {
        "request": WorkflowRequest(...),
    }

UnderstandRequestNode 调用：

    AgentContextBuilder.load_context_sources(...)
      → ConversationHistoryService.load_context_before_turn(...)

第一轮没有旧消息，因此：

    recent_history = []
    active_menu = None

## 3.5 第一轮真实 RequestFrame

以下是当前 RequestUnderstandingService 对该原文的实际输出：

    RequestFrame(
        tasks=(RequestTask(kind="menu_planning"),),
        memory_updates=(),
        current_constraints=(),
        turn_preferences=(),
        statements=(),
        participants=(),
        context_relation="new_task",
        operation=None,
        canonical=True,
        target=RequestTarget(
            recipe_name=None,
            ingredient=None,
            menu_category=None,
        ),
        requested_fields=(),
        exact_match_required=False,
        recommendation_count=12,
        servings=None,
        meal_type=None,
        scenario=None,
        menu_planning=MenuPlanningRequirements(
            category_quotas=(
                CategoryQuota(category="cold_dish", count=1),
                CategoryQuota(category="vegetarian", count=2),
                CategoryQuota(category="meat", count=3),
                CategoryQuota(category="hot_dish", count=4),
                CategoryQuota(category="staple", count=1),
                CategoryQuota(category="soup", count=1),
            ),
            distinct_recipes=True,
            allow_cross_category_counting=False,
        ),
        context_needs=(
            "allergies",
            "dietary_restrictions",
            "food_preferences",
        ),
        confidence=0.9,
        understanding_status="accepted",
        backend="rules",
        fallback_used=False,
        clarification_question=None,
        validation_errors=(),
    )

分类中英文映射：

    凉菜 → cold_dish
    素菜 → vegetarian
    荤菜 → meat
    热菜 → hot_dish
    主食 → staple
    汤   → soup

recommendation_count 的计算：

    1 + 2 + 3 + 4 + 1 + 1 = 12

distinct_recipes=True 表示不同配额不能重复使用同一道菜。

allow_cross_category_counting=False 表示一份候选只占一个分类配额。因此即使某道荤菜同时也是热菜，也不能同时抵扣 meat 和 hot_dish；本轮目标确实是 12 道不同菜。

### 当前发现：scenario 没有识别“农村流水席”

scenario 的真实值是：

    scenario = None

原因是 extract_menu_planning_requirements 当前只识别：

    "农村宴席", "婚宴", "宴席", "聚餐", "家宴"

输入中的“农村流水席”没有命中这些 marker。因为输入包含 6 个显式分类配额，所以仍然会正确进入 menu_planning，只是场景标签丢失。

## 3.6 UnderstandRequestNode 输出 WorkflowState

    {
        "request": WorkflowRequest(...),
        "request_frame": <上述 RequestFrame>,
        "recent_history": [],
        "active_menu": None,
    }

## 3.7 PrepareContextNode 和 AgentContext

PrepareContextNode 把预加载历史、长期记忆和 RequestFrame 装成：

    AgentContext(
        conversation_history=[],
        user_memories=<按 context_needs 加载的过敏/限制/偏好记忆>,
        user_profile=<运行时用户画像或 None>,
        dietary_constraints=None,
        requirements=None,
        resolved_constraints=None,
        intent=None,
        request_frame=<第一轮 RequestFrame>,
        episodic_memories=[],
        observations=[],
        context_metadata={
            "user_id": <AUTHENTICATED_USER_ID>,
            "session_id": <SESSION_ID>,
            "estimated_context_tokens": <运行时整数或 None>,
            "summarized_history_messages": 0,
            "loaded_context_types": <实际加载的上下文类型列表>,
            "request_understanding_backend": "rules",
            "request_understanding_confidence": 0.9,
            "understanding_status": "accepted",
            "request_tasks": ["menu_planning"],
            "context_needs": [
                "allergies",
                "dietary_restrictions",
                "food_preferences",
            ],
            "fallback_used": False,
        },
    )

user_memories 和 user_profile 依赖当前登录用户数据库数据，不能从三句输入推导。

## 3.8 resolve_constraints

输出到 WorkflowState：

    requirements = DietaryRequirements(...)
    resolved_constraints = ResolvedConstraints(...)
    context.requirements = requirements
    context.resolved_constraints = resolved_constraints
    context.dietary_constraints = hard_constraints(requirements).model_dump(...)

如果用户没有长期过敏、忌口或偏好，这些集合通常为空；如果数据库存在用户记忆，则本轮菜单必须继承安全约束。

## 3.9 Inner Agent 初始化

initialize_menu_task 根据 menu_planning 产生：

    MenuExecutionPlan(
        scenario=None,
        required={
            "cold_dish": 1,
            "vegetarian": 2,
            "meat": 3,
            "hot_dish": 4,
            "staple": 1,
            "soup": 1,
        },
        distinct_recipes=True,
        allow_cross_category_counting=False,
    )

初始进度：

    MenuTaskProgress(
        fulfilled={
            "cold_dish": 0,
            "vegetarian": 0,
            "meat": 0,
            "hot_dish": 0,
            "staple": 0,
            "soup": 0,
        },
        remaining={
            "cold_dish": 1,
            "vegetarian": 2,
            "meat": 3,
            "hot_dish": 4,
            "staple": 1,
            "soup": 1,
        },
        selected_recipes=(),
        candidate_pool=(),
        attempted_categories={
            "cold_dish": 0,
            "vegetarian": 0,
            "meat": 0,
            "hot_dish": 0,
            "staple": 0,
            "soup": 0,
        },
        exhausted_categories=(),
        coverage_history=(),
        complete=False,
        partial_reason="",
        excluded_recipe_ids=(),
        excluded_recipe_names=(),
    )

Inner AgentState 的其他关键字段：

    question = <第一轮原文>
    iteration = 0
    evidence_sufficient = False
    pending_calls = []
    tool_results = []
    route = "plan"
    tool_call_count = 0
    budget_exhausted = False
    loop_stop_reason = ""
    menu_execution_plan = <上述 plan 的 JSON>
    menu_task_progress = <上述 progress 的 JSON>

## 3.10 第一批 Planner ToolCall

Planner 按 remaining 从大到小排序，每批最多产生 4 个调用：

    ToolCall(
        id="menu-hot_dish-1",
        tool_name="search_recipes",
        arguments={
            "category": "hot_dish",
            "candidate_mode": True,
            "limit": 8,
            "exclude_recipe_ids": [],
            "exclude_recipe_names": [],
            "scope": "local",
        },
        purpose="为菜单的 hot_dish 配额批量召回候选菜。",
        success_criteria="返回至少 4 道未重复且通过硬约束的 hot_dish 候选。",
    )

    ToolCall(
        id="menu-meat-1",
        tool_name="search_recipes",
        arguments={
            "category": "meat",
            "candidate_mode": True,
            "limit": 6,
            "exclude_recipe_ids": [],
            "exclude_recipe_names": [],
            "scope": "local",
        },
        success_criteria="返回至少 3 道未重复且通过硬约束的 meat 候选。",
        ...
    )

    ToolCall(
        id="menu-vegetarian-1",
        tool_name="search_recipes",
        arguments={
            "category": "vegetarian",
            "candidate_mode": True,
            "limit": 5,
            "exclude_recipe_ids": [],
            "exclude_recipe_names": [],
            "scope": "local",
        },
        success_criteria="返回至少 2 道未重复且通过硬约束的 vegetarian 候选。",
        ...
    )

    ToolCall(
        id="menu-cold_dish-1",
        tool_name="search_recipes",
        arguments={
            "category": "cold_dish",
            "candidate_mode": True,
            "limit": 5,
            "exclude_recipe_ids": [],
            "exclude_recipe_names": [],
            "scope": "local",
        },
        success_criteria="返回至少 1 道未重复且通过硬约束的 cold_dish 候选。",
        ...
    )

limit 的公式：

    max(5, remaining * 2)

所以分别得到 8、6、5、5。

## 3.11 ToolResult、Observation 与菜单进度

每个 ToolCall 经 Executor 后形成 ToolResult，再由 Observer 规范化为：

    Observation(
        call_id="menu-meat-1",
        tool_name="search_recipes",
        purpose=<ToolCall.purpose>,
        success_criteria=<ToolCall.success_criteria>,
        ok=True或False,
        status="ok"或其他状态,
        has_data=True或False,
        summary=<结果摘要>,
        data={
            "items": [
                {
                    "id": <RECIPE_ID>,
                    "name": <RECIPE_NAME>,
                    "categories": ["meat", ...],
                    "main_ingredients": [...],
                    "ingredients": [...],
                    "ingredients_complete": True或False,
                    "safety_status": "eligible"或其他值,
                    ...
                }
            ],
            ...
        },
    )

Observer 为入选菜构造：

    SelectedMenuRecipe(
        recipe_id=<RECIPE_ID>,
        name=<RECIPE_NAME>,
        assigned_category="meat",
        categories=(...),
        credited_categories=("meat",),
        main_ingredients=(...),
        evidence_call_id="menu-meat-1",
    )

这里必须区分：

- categories：这道菜客观上属于哪些分类。
- assigned_category：本轮把它放在哪个配额。
- credited_categories：实际抵扣哪些配额；本项目当前禁止跨分类计数，所以只有 assigned_category。

如果第一批没有完成全部分类，下一轮 Planner 会继续为 remaining 大于 0 的分类生成 ToolCall。首次 scope="local"，第二次 attempt=2 时 scope="all"。

正常完整结果最终应为：

    fulfilled = {
        "cold_dish": 1,
        "vegetarian": 2,
        "meat": 3,
        "hot_dish": 4,
        "staple": 1,
        "soup": 1,
    }
    remaining = {
        "cold_dish": 0,
        "vegetarian": 0,
        "meat": 0,
        "hot_dish": 0,
        "staple": 0,
        "soup": 0,
    }
    complete = True

selected_recipes 中具体 recipe_id 和 name 由数据库决定。后续两轮会使用其中 assigned_category="meat" 的 3 条记录。

## 3.12 第一轮发布与持久化

最终发布前 check_final_safety 只允许通过 Dietary 复核的菜进入回答。

AgentProcessResponse 关键字段：

    status = "ok" 或证据不足时 "degraded"
    message = <最终菜单文本>
    route = <运行时路由>
    route_logic = "agent-tools-loop"
    sources = []
    error_code = None 或安全证据错误码
    recipe = None
    intent.kind = "menu_planning"
    metadata["menu_execution_plan"] = <plan>
    metadata["menu_task_progress"] = <progress>
    metadata["active_menu"] = {
        "plan": <plan>,
        "progress": <progress>,
    }

ChatTurnPersistence.save_agent_response 将 metadata 原样保存到第一轮 assistant message。active_menu 是第二轮能够“重新推荐荤菜”的核心结构化状态，不是从回答文本重新解析出来的。

# 四、第二轮：只替换荤菜

## 4.1 ChatRequest

    ChatRequest(
        message="请重新推荐荤菜",
        session_id=<SESSION_ID>,
        request_id=<新的客户端幂等ID或None>,
        user_id=<AUTHENTICATED_USER_ID>,
    )

## 4.2 ChatTurnStart

    ChatTurnStart(
        session_id=<SESSION_ID>,
        user_message_id=<U2>,
        response_order_index=<A2应使用的顺序>,
    )

start_turn 先保存第二轮用户消息，状态为 processing。

## 4.3 WorkflowRequest

    WorkflowRequest(
        user_id=<AUTHENTICATED_USER_ID>,
        message="请重新推荐荤菜",
        session_id=<SESSION_ID>,
        source_message_id=str(<U2>),
        history=[],
        context=None,
        use_user_memory=True,
        resume_approved=None,
    )

## 4.4 同事务读取 recent_history 与 active_menu

ConversationHistoryService.load_context_before_turn 读取 <U2> 之前的消息。

recent_history 逻辑内容为：

    [
        {"role": "user", "content": <第一轮原文>},
        {"role": "assistant", "content": <第一轮菜单回答>},
    ]

active_menu 从第一轮 assistant message 的 metadata["active_menu"] 得到：

    {
        "plan": {
            "scenario": None,
            "required": {
                "cold_dish": 1,
                "vegetarian": 2,
                "meat": 3,
                "hot_dish": 4,
                "staple": 1,
                "soup": 1,
            },
            "distinct_recipes": True,
            "allow_cross_category_counting": False,
        },
        "progress": {
            "fulfilled": <完整时全部等于 required>,
            "remaining": <完整时全部为0>,
            "selected_recipes": <第一轮12道菜>,
            ...
        },
    }

## 4.5 第二轮初始 RequestFrame

RequestUnderstandingService 的真实输出：

    RequestFrame(
        tasks=(RequestTask(kind="replace"),),
        memory_updates=(),
        current_constraints=(),
        turn_preferences=(),
        statements=(),
        participants=(),
        context_relation="modification",
        operation="replace",
        canonical=True,
        target=RequestTarget(
            recipe_name=None,
            ingredient=None,
            menu_category="meat",
        ),
        requested_fields=(),
        exact_match_required=False,
        recommendation_count=None,
        servings=None,
        meal_type=None,
        scenario=None,
        menu_planning=None,
        context_needs=(
            "allergies",
            "dietary_restrictions",
            "food_preferences",
        ),
        confidence=0.9,
        understanding_status="accepted",
        backend="rules",
        fallback_used=False,
        clarification_question=None,
        validation_errors=(),
    )

此时用户没有说“换几道”，所以 recommendation_count=None。

## 4.6 PrepareContextNode 继承原 meat quota

PrepareContextNode 从 active_menu["plan"]["required"]["meat"] 读取：

    inherited = 3
    count = frame.recommendation_count or inherited
    count = 3

它把 RequestFrame 改写为可执行的局部菜单计划：

    RequestFrame(
        tasks=(RequestTask(kind="menu_planning"),),
        context_relation="modification",
        operation="replace",
        target=RequestTarget(menu_category="meat", ...),
        recommendation_count=3,
        scenario=None,
        menu_planning=MenuPlanningRequirements(
            category_quotas=(
                CategoryQuota(category="meat", count=3),
            ),
            distinct_recipes=True,
            allow_cross_category_counting=False,
        ),
        ...
    )

注意：tasks 被改为 menu_planning，是因为 Agent Inner Runtime 需要复用确定性配额循环；operation 仍保留 replace，表示这不是一份全新菜单。

## 4.7 menu_modification

假设第一轮三道荤菜为：

    old_meat = [<旧荤菜1>, <旧荤菜2>, <旧荤菜3>]

其余九道菜为：

    preserved = [<凉菜1>, <素菜1>, <素菜2>, <热菜1..4>, <主食1>, <汤1>]

PrepareContextNode 写入：

    context.context_metadata["menu_modification"] = {
        "operation": "replace",
        "target_category": "meat",
        "requested_count": 3,
        "exclude_recipe_ids": [
            <旧荤菜1_ID>,
            <旧荤菜2_ID>,
            <旧荤菜3_ID>,
            <其余9道菜的ID>,
        ],
        "exclude_recipe_names": [
            <旧荤菜1_NAME>,
            <旧荤菜2_NAME>,
            <旧荤菜3_NAME>,
            <其余9道菜的名称>,
        ],
        "replaced_recipe_ids": [
            <旧荤菜1_ID>,
            <旧荤菜2_ID>,
            <旧荤菜3_ID>,
        ],
        "replaced_recipe_names": [
            <旧荤菜1_NAME>,
            <旧荤菜2_NAME>,
            <旧荤菜3_NAME>,
        ],
    }

为什么 exclude 包含全部 12 道旧菜：

- 旧 3 道荤菜必须避免原样返回。
- 保留的 9 道菜也必须排除，否则新荤菜可能与保留菜单重复。

为什么 replaced 只有 3 道：

- 它用于审计“这次真正替换了什么”。
- 非荤菜只是去重保护，并没有被替换。

## 4.8 第二轮 Inner Agent 初始化

新的局部 MenuExecutionPlan：

    {
        "scenario": None,
        "required": {"meat": 3},
        "distinct_recipes": True,
        "allow_cross_category_counting": False,
    }

新的局部 MenuTaskProgress：

    {
        "fulfilled": {"meat": 0},
        "remaining": {"meat": 3},
        "selected_recipes": [],
        "attempted_categories": {"meat": 0},
        "complete": False,
        "excluded_recipe_ids": <第一轮全部12道菜ID>,
        "excluded_recipe_names": <第一轮全部12道菜名>,
        ...
    }

## 4.9 第二轮 ToolCall

    ToolCall(
        id="menu-meat-1",
        tool_name="search_recipes",
        arguments={
            "category": "meat",
            "candidate_mode": True,
            "limit": 6,
            "exclude_recipe_ids": <第一轮全部12道菜ID>,
            "exclude_recipe_names": <第一轮全部12道菜名>,
            "scope": "local",
        },
        purpose="为菜单的 meat 配额批量召回候选菜。",
        success_criteria="返回至少 3 道未重复且通过硬约束的 meat 候选。",
    )

如果本地来源不足，第二次尝试为：

    id = "menu-meat-2"
    scope = "all"

## 4.10 第二轮完成与 active_menu 合并

局部 progress 完成时：

    selected_recipes = [
        <新荤菜1, assigned_category="meat">,
        <新荤菜2, assigned_category="meat">,
        <新荤菜3, assigned_category="meat">,
    ]
    fulfilled = {"meat": 3}
    remaining = {"meat": 0}
    complete = True

AgentExecutionService 不直接用局部菜单覆盖旧菜单，而是调用：

    merge_active_menu_replacement(
        previous_active=<第一轮完整 active_menu>,
        replacement_plan_payload=<第二轮局部 plan>,
        replacement_progress_payload=<第二轮局部 progress>,
        modification=<menu_modification>,
    )

合并规则：

    preserved = 第一轮所有 assigned_category != "meat" 的菜
    selected = preserved + 第二轮新荤菜

然后对完整 required 重新计算 fulfilled、remaining、complete。

第二轮 assistant metadata 中新的 active_menu 仍是完整 12 道菜单：

    active_menu["plan"]["required"] = 原六分类配额
    active_menu["progress"]["selected_recipes"] =
        <保留的9道菜> + <新荤菜1> + <新荤菜2> + <新荤菜3>

这一步保证第三轮“第三个荤菜”看到的是替换后的荤菜，不是第一轮旧荤菜。

# 五、第三轮：查询替换后第三个荤菜的步骤

## 5.1 ChatRequest

    ChatRequest(
        message="第三个荤菜怎么做？",
        session_id=<SESSION_ID>,
        request_id=<新的客户端幂等ID或None>,
        user_id=<AUTHENTICATED_USER_ID>,
    )

## 5.2 recent_history 与 active_menu

读取 <U3> 之前的历史，逻辑上包含：

    [
        {"role": "user", "content": <第一轮原文>},
        {"role": "assistant", "content": <第一轮菜单回答>},
        {"role": "user", "content": "请重新推荐荤菜"},
        {"role": "assistant", "content": <第二轮替换结果回答>},
    ]

active_menu 来自第二轮 assistant metadata，内容是“保留9道 + 新3道荤菜”的完整菜单。

## 5.3 第三轮初始 RequestFrame

RequestUnderstandingService 在只看当前原文时实际产生：

    RequestFrame(
        tasks=(RequestTask(kind="recipe_detail"),),
        memory_updates=(),
        current_constraints=(),
        turn_preferences=(),
        statements=(),
        participants=(),
        context_relation="new_task",
        operation=None,
        canonical=True,
        target=RequestTarget(
            recipe_name="第三个荤菜",
            ingredient=None,
            menu_category=None,
        ),
        requested_fields=("steps",),
        exact_match_required=True,
        recommendation_count=None,
        servings=None,
        meal_type=None,
        scenario=None,
        menu_planning=None,
        context_needs=("recent_conversation",),
        confidence=0.9,
        understanding_status="accepted",
        backend="rules",
        fallback_used=False,
        clarification_question=None,
        validation_errors=(),
    )

这里的 context_relation 暂时是 new_task，因为规则理解阶段把“第三个荤菜”当成了一个具体目标字符串。它还没有读取 active_menu。

## 5.4 PrepareContextNode 结构化引用解析

PrepareContextNode 调用：

    resolve_active_menu_recipe_reference(
        message="第三个荤菜怎么做？",
        active_menu=<第二轮完整活动菜单>,
    )

函数处理：

    ordinal = 3
    category = "meat"
    category_recipes = [
        item
        for item in active_menu["progress"]["selected_recipes"]
        if item["assigned_category"] == "meat"
    ]
    referenced_name = category_recipes[2]["name"]

因此 referenced_name 的真实值是：

    referenced_name = <新荤菜3_NAME>

它不是回答文本中的第三行，也不是全部 12 道菜的第三道，而是 selected_recipes 中 assigned_category="meat" 子序列的第三条。

PrepareContextNode 将 RequestFrame 更新为：

    RequestFrame(
        tasks=(RequestTask(kind="recipe_detail"),),
        context_relation="reference",
        target=RequestTarget(
            recipe_name=<新荤菜3_NAME>,
            ingredient=None,
            menu_category=None,
        ),
        requested_fields=("steps",),
        exact_match_required=True,
        ...
    )

这才是进入 Inner Agent 的最终 RequestFrame。

## 5.5 IntentDecision

intent_from_request_frame 看到：

    primary_task == "recipe_detail"
    target.recipe_name == <新荤菜3_NAME>
    requested_fields == ("steps",)
    exact_match_required == True

因此确定性返回：

    IntentDecision(
        kind="recipe_detail",
        reason="complete_detail_contract",
        clarification="",
    )

这里不需要小模型重新猜意图。

## 5.6 第三轮精确查询 ToolCall

Planner 生成：

    ToolCall(
        id="exact-recipe-search",
        tool_name="search_recipes",
        arguments={
            "name_contains": <新荤菜3_NAME>,
            "exact_name": True,
            "required_fields": ["steps"],
            "limit": 1,
        },
        purpose="查询用户明确指定的食谱",
        success_criteria="按数据源优先级返回该菜或明确NOT_FOUND/ERROR",
    )

这里不会把“第三个荤菜”传给搜索工具。工具收到的 name_contains 已经是活动菜单中的真实菜名。

## 5.7 RecipeQuery

SearchRecipesTool 使用 RecipeQuery 二次校验 ToolCall.arguments。关键字段为：

    RecipeQuery(
        name_contains=<新荤菜3_NAME>,
        exact_name=True,
        required_fields=("steps",),
        limit=1,
        include_ingredients=(),
        exclude_ingredients=(),
        category=None,
        candidate_mode=False,
        exclude_recipe_ids=(),
        exclude_recipe_names=(),
        scope="local",
        ...
    )

exact_name=True 表示不能用相似菜替代。

required_fields=("steps",) 表示即使找到菜名，但没有步骤，也应返回 FIELD_MISSING，而不是假装完整回答。

## 5.8 Tool Observation

找到完整做法时：

    Observation(
        call_id="exact-recipe-search",
        tool_name="search_recipes",
        ok=True,
        status="ok",
        has_data=True,
        data={
            "status": "FOUND",
            "exact_name": True,
            "items": [
                {
                    "name": <新荤菜3_NAME>,
                    "ingredients": [...],
                    "steps": <真实步骤>,
                    ...
                }
            ],
            "missing_fields": [],
            ...
        },
        ...
    )

找到菜但缺步骤时：

    status = "FIELD_MISSING"
    missing_fields = ["steps"]

菜名不存在时：

    status = "NOT_FOUND"
    items = []

外部来源故障时：

    status = "ERROR"
    errors = [...]

deterministic_evidence_is_sufficient 会把 FOUND、FIELD_MISSING、NOT_FOUND、ERROR 都视为“已经得到确定结论”，因此不会无限重复搜索。

## 5.9 第三轮最终响应

成功时 AgentProcessResponse 的关键字段：

    intent.kind = "recipe_detail"
    status = "ok"
    message = <新荤菜3的步骤回答>
    route_logic = "agent-tools-loop"
    metadata["active_menu"] = <继续保留第二轮完整菜单>
    metadata["safety_review"] = "passed" 或按证据为 "unknown"/"blocked"

即使第三轮只是查询做法，AgentExecutionService 也会保留 previous_active，避免用空菜单计划覆盖会话中的活动菜单。

# 六、三轮字段变化对照

| 字段 | 第一轮 | 第二轮理解后 | 第二轮装配后 | 第三轮理解后 | 第三轮装配后 |
|---|---|---|---|---|---|
| tasks[0].kind | menu_planning | replace | menu_planning | recipe_detail | recipe_detail |
| context_relation | new_task | modification | modification | new_task | reference |
| operation | None | replace | replace | None | None |
| target.menu_category | None | meat | meat | None | None |
| target.recipe_name | None | None | None | 第三个荤菜 | <新荤菜3_NAME> |
| requested_fields | () | () | () | (steps,) | (steps,) |
| exact_match_required | False | False | False | True | True |
| recommendation_count | 12 | None | 3 | None | None |
| menu_planning | 六分类12道 | None | meat=3 | None | None |
| active_menu | None | 第一轮完整菜单 | 第一轮完整菜单 | 第二轮完整菜单 | 第二轮完整菜单 |

# 七、最容易混淆的字段

## 7.1 request_frame.menu_planning 与 menu_execution_plan

- request_frame.menu_planning：用户需求契约。
- menu_execution_plan：进入 Inner Agent 后的可执行、可检查点化目标。

第一轮两者都包含六分类；第二轮 RequestFrame 被改写为 meat=3 的局部任务，而最终 active_menu 会再与旧完整菜单合并。

## 7.2 menu_task_progress 与 active_menu

- menu_task_progress：当前这一次 Agent 执行的进度。
- active_menu：跨轮保存的完整菜单状态。

第二轮 menu_task_progress 只有 3 道新荤菜；第二轮保存的 active_menu 则仍包含完整 12 道菜。

## 7.3 categories、assigned_category、credited_categories

- categories：菜谱自身可归属的所有分类。
- assigned_category：本次选择时放入的主分类。
- credited_categories：实际计入的配额分类。

第三轮的“第三个荤菜”按 assigned_category 过滤。

## 7.4 recent_history 与 active_menu

- recent_history：用于语言理解的 user/assistant 文本。
- active_menu：用于菜单修改和顺序引用的结构化元数据。

“第三个荤菜”优先依据 active_menu，不依赖自然语言回答的排版。

## 7.5 exclude_recipe_ids 与 replaced_recipe_ids

- exclude_recipe_ids：第二轮所有不能再次选中的菜，正常是旧完整菜单的全部 12 道。
- replaced_recipe_ids：真正被替换的旧荤菜，正常只有 3 道。

## 7.6 requested_fields 与 required_fields

- RequestFrame.requested_fields：用户要查哪些内容，本轮为 steps。
- RecipeQuery.required_fields：传给 Recipe Service 的字段完整性要求，同样为 steps。

# 八、这次追踪发现的实际注意点

1. “农村流水席”会进入正确的 12 道菜单规划，但 scenario 当前为 None。
2. 第二轮必须能从上一轮 assistant metadata 读取 active_menu；只有回答文本不够。
3. 第二轮最终保存的是合并后的完整菜单，不是只有 3 道新荤菜的局部进度。
4. 第三轮初始 RequestFrame 会暂时把 recipe_name 写成“第三个荤菜”，随后 PrepareContextNode 使用 active_menu 改成真实菜名。
5. 第三轮精确搜索要求 steps；找不到步骤时必须返回 FIELD_MISSING，不能重复推荐这道菜的材料来替代做法。
