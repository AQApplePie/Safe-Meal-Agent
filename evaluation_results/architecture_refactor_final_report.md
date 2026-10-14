# SafeMeal Physical Architecture Refactor 最终报告

## 1. Original Architecture Problems

原 application/ 同时容纳 Agent 内层循环、外层 Workflow、聊天持久化、Recipe、Dietary、Identity、Knowledge、Tool 和 Composition Root。职责虽然在逻辑上部分分离，但查找一个能力需要跨多个技术目录，并且共享业务代码会直接看见 Agent 契约。

## 2. New Module Boundaries

- agent/：请求理解、结构化上下文、Agent 安全适配、Outer Workflow、Inner Runtime、模型协议与 Tool Adapter。
- modules/recipe/：菜谱查询、分类、生成契约、应用服务和端口。
- modules/dietary/：可复用的约束、taxonomy、偏好与确定性安全规则。
- modules/identity/：现有注册、登录、令牌与认证端口。
- modules/knowledge/：上传、解析、分块、摄取和检索用例及端口。
- modules/conversation/：会话、消息事务和用户长期记忆。
- infrastructure/：MySQL、LLM、NLU、检索、摄取和安全技术实现。
- interfaces/：HTTP、认证依赖和 SSE 传输。
- bootstrap/：跨模块依赖装配的唯一位置。

## 3. Key Decisions

Recipe 不是 Agent 子模块，因为菜谱事实、查询和详情可以由普通 API 与后台任务复用。Dietary 的 taxonomy 和确定性判定同样是共享业务能力；只有直接读取 AgentContext/Observation 的发布安全适配位于 agent/safety/。

agent/workflow/ 保留外层控制面，agent/runtime/orchestration/ 保留 Planner → Execute → Observe → Reflect 内层循环，未因目录整理而合并两张图。

Tool 被限定为 schema、registry、dispatch 以及 Tool → Application Service 适配，不直接访问 SQL、Redis 或实现饮食领域规则。本次仍是进程内模块化单体；拆微服务会扩大部署和失败边界，不属于物理整理。

## 4. Migration Map

完整路径映射见 docs/architecture/module_migration_map.md。

## 5. Compatibility Layer

没有新增旧路径 re-export，也没有复制实现。checkpoint_serializer.py 中保留的旧模块名字符串仅用于读取历史持久化 checkpoint，不是可导入的兼容代码路径。

## 6. Dependency Direction

AST 架构测试验证：

- modules → agent：0
- modules → LangGraph：0
- modules → infrastructure：0
- 具体 Infrastructure 只由 bootstrap/、main.py 或 Infrastructure 自身引用。

Recipe 生成对模型的类型依赖被收窄为 RecipeGenerator port；具体 LLM gateway 在 Composition Root 注入。

## 7. Tests

- 重构前：243 passed，1 skipped。
- Agent/refactor：166 passed。
- evaluation：74 passed。
- 最终全部测试：240 passed，1 skipped。
- Ruff：通过。
- 应用构造：SafeMeal Agent，34 条路由，成功。

最终总数比基线少 3 项，是因为原架构测试中验证“不得存在 modules 目录”等旧物理结构断言被替换为新架构依赖断言；业务测试未删除。

## 8. Behavior Changes

NONE。仅改变文件位置、导入、包出口、类型端口和 Composition Root 路径。

## 9. New Business Features

NONE。modules/interaction/ 只有边界说明，没有 Favorite、Like、ViewHistory、Ranking 或任何假实现。

## 10. Remaining Architecture Debt

- checkpoint_serializer.py 仍需识别历史 checkpoint 的旧模块名；删除会破坏已有持久化数据兼容。
- AgentModelGateway 仍同时表达规划、反思、回答和生成能力；Recipe 已通过最小 RecipeGenerator port 与其解耦，但未来可在独立任务中继续做接口隔离。
- 本次验证了应用对象可构造；依赖真实 MySQL、Redis、Milvus、Neo4j 和外部模型的容器级 E2E 仍取决于本地服务健康状态。
