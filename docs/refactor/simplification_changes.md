# 减法重构变更

## 删除

- 删除 Initializer 的 `_conversation_from_messages`。
- 删除 `create_initializer_node.history_messages`、`build_agent_graph.history_messages`、组合根传参和 `AGENT_HISTORY_MESSAGES` 配置。
- 删除 PrepareContext 的第二次规则理解和第二次上下文源加载兼容分支。
- 删除 AgentState 的 `human_approved`、`approval_required`、`safety_gate_blocked`。
- 删除 AgentContext/WorkflowState 的 `resolved_constraints` 副本及写入。
- 删除 RecipeQuery 的 `candidate_limit` 外部参数及 Planner 的 `candidate_limit/limit` 计算传递。

## 收敛后的责任边界

- Understanding：唯一生成 Canonical RequestFrame；规则模型是该入口内部 fallback。
- Context Preparation：加载可信上下文、解析结构化菜单引用，不分类新请求。
- Constraint Resolution：唯一生成 DietaryRequirements。
- Initializer：验证并装配可信状态。
- Planner：选择下一步行动；不拥有检索扫描规模。
- RecipeService：拥有候选召回规模策略。
- Observer：把执行结果变成证据并更新进度。
- Reflector：决定完成、继续或停止。
- Dietary 模块：提供唯一食材/约束判断规则；Agent Safety 只控制发布。

## 兼容契约变化

直接调用 PrepareContextNode 必须提供 RequestFrame；直接调用 Inner Agent 若希望继承历史与约束，必须通过 AgentContext 提供。HTTP/Outer Workflow 契约未变化。


## 本次新增实质修改

起点是已有未提交改动的工作区，前轮删除不计入本次增量。

- 删除函数：Initializer._context_observations、render_review_reply、ConversationHistoryService.load_before_turn、load_active_menu_before_turn、AgentContextBuilder._json_objects。
- 删除参数：DietarySafetyService.resolve_constraints.history；保留历史上下文测试数据，迁入既有 context 字段。
- 删除分支/重复逻辑：resume 独立 response 组装、独立并发/超时调用；Responder 完成度扫描；assessment 无效果的上下文预过滤；重复中文数量表；Initializer 静默生成空 requirements。
- 合并责任：既有 DietarySafetyService 负责 Frame 硬约束与缺 Frame 文本 fallback；Workflow、独立 Gateway 消费同一个方法。Initializer 只准备状态并检查输入契约。
- Planner 共用预算快照与状态写回，保留动态 plan、确定性数量/精确查询/菜单行动和统一工具闸门。
- 没有删除文件或本轮状态字段；未新增 Graph Node、双路由、Policy Framework、数据库结构或 migration。
- process/resume 共用真实结果分类、recipe 验证、完整 trace、menu active state、展示引用和推荐完成度。resume timeout 分类为 agent_timeout，排队时间也计入 timeout。
- 新增 8 项必要回归；既有断言未删除或弱化。


## 静态验收修复

修复 31 项原有 mypy 错误，保留原运行行为与 Pydantic 校验；没有添加 ignore/Any。仅格式化本轮造成新差异的两个原本格式合规文件及新测试，既有 121 项格式债务单独记录。
