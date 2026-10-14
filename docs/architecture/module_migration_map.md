# 模块迁移映射

以下记录主要物理迁移；同目录内的包入口与配套契约随所属模块一并迁移。

| OLD PATH | NEW PATH | Reason |
|---|---|---|
| application/agent/ | agent/runtime/ | 内层 Planner → Execute → Observe → Reflect 决策循环属于 Agent Runtime。 |
| application/agent/gateway/ | agent/gateway/ | 对外执行入口独立于内层循环。 |
| application/workflow/ | agent/workflow/ | 保留理解、上下文、约束、调用、安全和记忆组成的外层控制面。 |
| application/contracts/agent/ | agent/contracts/ | Agent 状态、决策和 API 契约由 Agent 所有。 |
| application/contracts/workflow/models.py、stream.py | agent/contracts/workflow/ | 只服务外层 Agent Workflow。 |
| application/contracts/workflow/request_frame.py、semantic.py | shared/contracts/ | Recipe 与 Dietary 同时消费，放入共享契约可消除业务模块对 Agent 的反向依赖。 |
| application/service/chat/ 中的理解代码 | agent/understanding/ | 自然语言到 RequestFrame 的解释属于 Agent intelligence。 |
| application/service/chat/ 中的活动菜单、历史、菜单规划和短期指代 | agent/context/ | 维护 Agent 可继续执行的结构化会话状态。 |
| application/service/chat/chat_turn_service.py | agent/gateway/chat_turn_service.py | 直接调用 Agent Workflow，是接口到 Agent 的协调入口。 |
| application/service/chat/chat_session_service.py、turn_persistence.py | modules/conversation/application/ | 会话查询和消息事务是可独立于 Agent 的传统应用能力。 |
| application/contracts/chat/、conversation/、memory/ | modules/conversation/contracts/ | 会话和用户记忆是共享业务契约。 |
| application/service/memory/ | modules/conversation/application/memory/ | 用户长期记忆随会话业务模块管理。 |
| application/contracts/recipes/ | modules/recipe/contracts/ | 菜谱数据与查询契约属于 Recipe 业务事实。 |
| application/service/recipes/ 中的 RecipeService、分类和食物类别 | modules/recipe/application/ | 可由 Agent 之外的入口复用。 |
| application/service/recipes/dietary_filter.py | modules/dietary/application/ | 过滤依据是饮食约束而非 Recipe CRUD。 |
| application/service/recipes/menu_coverage.py、menu_output.py | agent/runtime/ | 菜单目标完成度和最终表达只服务 Agent 执行。 |
| Recipe repository/provider ports | modules/recipe/ports/ | Recipe 模块声明所需技术能力。 |
| application/contracts/dietary_safety/ | modules/dietary/contracts/ | 饮食约束与安全证据是共享业务契约。 |
| 通用 Dietary 规则与 taxonomy | modules/dietary/application/ | 普通 Recipe API 与 Agent 均可复用。 |
| 读取 AgentContext/Observation 的 Dietary 服务与回答渲染 | agent/safety/ | Agent 专用安全适配不应污染共享模块。 |
| Auth contracts/services/ports | modules/identity/ | 身份认证形成独立业务边界。 |
| Knowledge、Upload contracts/services/ports | modules/knowledge/ | 文档摄取与知识检索是独立业务能力。 |
| application/tool/ | agent/runtime/tools/adapters/ | Tool 只负责把 Agent 调用适配到应用服务。 |
| application/agent/tools/ | agent/runtime/tools/ | Tool 注册、策略与执行运行时统一收敛。 |
| application/ports/tools/ | agent/runtime/tools/ports/ | Tool handler/executor 协议与运行时共同归属 Agent。 |
| application/service/composition/ | bootstrap/composition/ | 跨模块和基础设施的依赖只在进程装配根完成。 |
| application/exceptions.py | shared/exceptions.py | 多业务模块共同使用的异常契约。 |

未建立旧路径 compatibility re-export；项目内部、测试和脚本已一次性迁移到新路径。
