# SafeMeal 目标物理架构

## 1. Module Ownership

- `modules/recipe/`：菜谱查询、详情、分类、生成等业务事实和应用服务。
- `modules/dietary/`：饮食约束、食材 taxonomy、偏好、安全证据和确定性判定。
- `modules/identity/`：现有注册、登录、令牌与认证能力。
- `modules/knowledge/`：上传文档、分块、摄取、索引和知识检索用例。
- `modules/conversation/`：会话、消息、轮次持久化和用户记忆应用能力。
- `modules/interaction/`：未来 Recipe Platform 交互能力的边界说明，本次没有实现。
- `agent/`：请求理解、上下文准备、外层控制平面、内层决策循环和 Tool Adapter。
- `interfaces/`：HTTP、SSE 等传输协议适配。
- `infrastructure/`：数据库、模型供应商、NLU、检索、摄取和安全技术实现。
- `bootstrap/`：唯一的跨模块 Composition Root。

## 2. Dependency Rules

```text
Interfaces → Modules Application / Agent Gateway
Agent → Modules Application Services / Module Contracts / Module Ports
Modules Application → Module Contracts / Module Ports
Infrastructure → implements Agent or Module Ports
Bootstrap → assembles all concrete implementations
```

禁止：

```text
modules/* → agent/*
modules/* → LangGraph
modules/* → infrastructure/*
domain contracts → LLM SDK
```

## 3. Agent Layers

```text
Agent Outer Workflow
  understand → context → constraints → invoke/resume → final safety → memory
                         ↓
Agent Inner Runtime
  initialize → plan → execute → observe → reflect → respond
```

两层图具有不同生命周期和信任边界，物理迁移后仍保持分离。

## 4. Shared Domain Rule

Web、Agent 和 Worker 可以共同依赖 `modules/*` 的 contract、application service 与 port。共享业务模块不能依赖 Agent 状态、LangGraph、HTTP 请求或具体基础设施客户端。

## 5. Future Recipe Platform

平台边界包括 Recipe、Dietary、Identity 与 Interaction。此架构审计原始阶段只规划 Interaction；截至 2026-10-09，收藏、点赞、浏览历史、排行和用户行为事件已有实现，且新增独立 `safemeal.platform_main` 入口。最新运行与验收说明见 `docs/optimization/01_backend_independent_runtime.md`。

## 6. Future Service Extraction

当前 Agent Tool 通过进程内 Application Service 获取业务能力：

```text
Agent Tool → Local Application Service
```

未来若 Recipe Platform 独立部署，只替换 Tool 后面的端口实现：

```text
Agent Tool → Recipe Platform Client
```

Agent 的 Tool schema、Planner 和业务模块契约不需要因此改写。本次不创建 HTTP 微服务客户端。

