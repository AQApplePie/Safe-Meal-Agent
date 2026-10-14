# 当前模块职责清单

本清单基于实际 import、Composition Root 装配和运行调用链，而不是仅根据文件名分类。

| 原文件路径 | 类别 | 当前职责 | 目标模块 | 建议移动 | 主要依赖 | 主要调用方 | 风险 |
|---|---|---|---|---|---|---|---|
| `application/agent/` | AGENT_ONLY | 内层 Agent 运行循环、模型协议、工具治理、回答汇聚 | `agent/runtime/` | 是 | Agent contracts、Recipe/Dietary 服务、LLM port | Agent gateway | 高 |
| `application/workflow/` | AGENT_ONLY | 外层控制平面：理解、上下文、约束、调用、发布复核、记忆 | `agent/workflow/` | 是 | understanding、context、dietary、Agent gateway | Chat workflow runner | 高 |
| `application/contracts/agent/` | AGENT_ONLY | Agent 状态、决策、预算、上下文和 API 契约 | `agent/contracts/` | 是 | shared、部分通用 contract | Agent runtime/workflow | 高 |
| `application/contracts/workflow/` | AGENT_ONLY / SHARED_APPLICATION | WorkflowState 与流事件属于 Agent；RequestFrame 与通用语义同时被业务模块消费 | `agent/contracts/workflow/`、`shared/contracts/` | 是 | dietary preference contract | Outer Workflow、NLU、Recipe、Dietary | 高 |
| `application/ports/agent.py` | AGENT_ONLY | Chat 对 Agent 的唯一调用端口 | `agent/contracts/ports.py` | 是 | Agent API contract | Chat turn service | 中 |
| `application/ports/request_understanding.py` | AGENT_ONLY | 可替换请求理解后端端口 | `agent/understanding/port.py` | 是 | RequestFrame | understanding node、NLU adapter | 中 |
| `application/service/chat/request_understanding.py` | AGENT_ONLY | 规则请求理解和降级 | `agent/understanding/` | 是 | RequestFrame、menu/context helpers | Outer Workflow、NLU adapter | 高 |
| `application/service/chat/negation_scope.py` | AGENT_ONLY | RequestFrame 否定语义归一化 | `agent/understanding/` | 是 | food category、RequestFrame | request understanding | 中 |
| `application/service/chat/request_frame_semantics.py` | AGENT_ONLY | RequestFrame 跨字段规范化 | `agent/understanding/` | 是 | dietary/workflow contracts | NLU、rule understanding | 高 |
| `application/service/chat/active_menu.py` | AGENT_ONLY | 合并跨轮活动菜单状态 | `agent/context/` | 是 | menu plan/progress、coverage | Agent gateway | 中 |
| `application/service/chat/short_term_reference.py` | AGENT_ONLY | 解析近期菜谱指代 | `agent/context/` | 是 | conversation contract | request understanding、NLU | 中 |
| `application/service/chat/conversation_history_service.py` | AGENT_ONLY | 加载 Agent 所需历史和活动菜单 | `agent/context/` | 是 | Chat repository port | context builder | 中 |
| `application/service/chat/menu_planning.py` | AGENT_ONLY | 解析菜单配额、修改和结构化引用 | `agent/context/` | 是 | RequestFrame | understanding、prepare context | 高 |
| `application/service/chat/chat_session_service.py` | SHARED_APPLICATION | 会话查询与管理用例 | `modules/conversation/application/` | 是 | Chat repository port | HTTP chat router | 中 |
| `application/service/chat/chat_turn_service.py` | AGENT_ONLY | 持久化一轮聊天并调用 Agent workflow，是 HTTP 与 Agent 的用例协调入口 | `agent/gateway/` | 是 | Agent workflow、turn persistence | HTTP chat router | 高 |
| `application/service/chat/turn_persistence.py` | SHARED_APPLICATION | 消息和轮次事务协调 | `modules/conversation/application/` | 是 | Chat UoW port | ChatTurnService | 中 |
| `application/contracts/chat/`、`conversation/` | SHARED_APPLICATION | 会话、消息、回答和轮次契约 | `modules/conversation/contracts/` | 是 | shared JSON types | Agent、HTTP、persistence | 高 |
| `application/ports/persistence/chat_repository.py` | SHARED_APPLICATION | 会话持久化端口与事务边界 | `modules/conversation/ports/` | 是 | conversation contracts | conversation services、SQL adapter | 高 |
| `application/contracts/recipes/` | RECIPE_DOMAIN | 菜谱查询、详情、生成和候选契约 | `modules/recipe/contracts/` | 是 | shared、菜单分类类型 | Recipe service、Agent tools | 高 |
| `application/service/recipes/recipe_service.py` | RECIPE_DOMAIN | 菜谱查询、详情、推荐与生成用例 | `modules/recipe/application/` | 是 | Recipe repository/provider、分类和过滤服务 | Agent recipe tools | 高 |
| `application/service/recipes/classification.py`、`food_category.py` | RECIPE_DOMAIN | 基于可信菜谱字段派生分类 | `modules/recipe/application/` | 是 | recipe contracts | RecipeService、menu search | 中 |
| `application/service/recipes/dietary_filter.py` | DIETARY_DOMAIN | 按饮食限制过滤结构化菜谱 | `modules/dietary/application/` | 是 | dietary taxonomy | RecipeService | 中 |
| `application/service/recipes/menu_coverage.py` | AGENT_ONLY | Agent 菜单配额完成度 | `agent/runtime/menu/` | 是 | Agent menu contracts | observer、final safety、active menu | 高 |
| `application/service/recipes/menu_output.py` | AGENT_ONLY | 把 Agent 菜单进度渲染为回答 | `agent/runtime/menu/` | 是 | Agent menu contracts | responder、final safety | 中 |
| `application/ports/persistence/recipe_repository.py`、`ports/recipes/` | RECIPE_DOMAIN | 菜谱持久化和外部来源端口 | `modules/recipe/ports/` | 是 | recipe contracts | RecipeService、infrastructure | 高 |
| `application/contracts/dietary_safety/` | DIETARY_DOMAIN | 约束、证据、安全判定和要求契约 | `modules/dietary/contracts/` | 是 | shared | Recipe、Agent、Dietary service | 高 |
| `application/service/dietary_safety/` | DIETARY_DOMAIN / AGENT_ONLY | taxonomy、偏好和确定性评估可复用；直接读取 AgentContext/Observation 的服务与回答渲染只属于 Agent | `modules/dietary/application/`、`agent/safety/` | 是 | dietary/recipe/agent contracts | Agent final safety、RecipeService | 高 |
| `application/tool/constraint_verification.py`、`dietary_search.py` | AGENT_ONLY | Dietary Application Service 的 Agent Tool 适配 | `agent/runtime/tools/adapters/` | 是 | dietary service/backend port | Tool registry | 中 |
| `application/tool/recipe_tools.py` | AGENT_ONLY | Recipe Application Service 的 Agent Tool 适配 | `agent/runtime/tools/adapters/` | 是 | RecipeService | Tool registry | 中 |
| `application/tool/knowledge_search.py` | AGENT_ONLY | Knowledge Application Service 的 Agent Tool 适配 | `agent/runtime/tools/adapters/` | 是 | DocumentKnowledgeService | Tool registry | 中 |
| `application/agent/tools/`、`application/ports/tools/` | AGENT_ONLY | Tool schema、registry、policy、dispatch 和 handler 协议 | `agent/runtime/tools/` | 是 | Agent contracts | runtime executor、container | 高 |
| `application/contracts/auth/`、`service/auth/`、auth repository port | IDENTITY_DOMAIN | 注册、登录、令牌与认证持久化契约 | `modules/identity/` | 是 | security port | Auth HTTP、SQL/security adapters | 高 |
| `application/service/knowledge/`、`service/upload/`、upload contracts | KNOWLEDGE_DOMAIN | 文档保存、解析、分块、索引和混合检索 | `modules/knowledge/` | 是 | ingestion/retrieval ports | Knowledge HTTP、Agent tool | 高 |
| `application/service/memory/`、memory contracts/port | SHARED_APPLICATION | 用户长期记忆业务 | `modules/conversation/` | 是 | memory repository port | Outer Workflow | 高 |
| `application/service/composition/` | SHARED_APPLICATION | 进程级依赖装配 | `bootstrap/` | 是 | 所有模块端口与 infrastructure | `main.py`、HTTP dependencies | 高 |
| `infrastructure/*` | INFRASTRUCTURE | SQL、模型、NLU、检索、安全和摄取技术实现 | 保持 `infrastructure/` | 否 | modules/agent ports | Composition Root | 中 |
| `interfaces/http/*` | INTERFACE | HTTP、SSE、认证依赖和路由 | 保持 `interfaces/http/` | 否 | modules/agent application entry | 外部客户端 | 中 |
| `application/runtime_budget.py`、`streaming.py`、`exceptions.py` | UNCERTAIN | 跨 Agent、Interface 的运行期支持 | `agent/runtime/` 或 `shared/` | 分别判断 | contracts/contextvars | Agent gateway、HTTP SSE | 中 |

## 结论

- `modules/conversation/` 承载会话、消息和用户记忆；直接调用 Agent Workflow 的单轮协调入口归入 `agent/gateway/`。
- RequestFrame 和通用语义契约放入 `shared/contracts/`，避免 Recipe/Dietary 反向依赖 Agent。
- Outer Workflow 与 Inner Runtime 必须分别放在 `agent/workflow/` 和 `agent/runtime/orchestration/`。
- Recipe、Dietary、Identity、Knowledge 均可独立服务于 Agent 之外的调用方，不能归入 Agent。
- 四套旧 Tool 目录应收敛到 `agent/runtime/tools/`；具体基础设施仍通过模块端口提供。
